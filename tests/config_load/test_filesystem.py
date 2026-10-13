"""Reading the file from disk."""

import errno
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from space.config import ConfigError, load_config

from .helpers import NOT_REGULAR, assert_error, rejected, write

# Captured at import, before any test patches `os`; the FIFO writer and teardown use only these.
_REAL_OPEN = os.open
_REAL_CLOSE = os.close
_REAL_WRITE = os.write


class Watch:
    """Descriptors opened on one path, plus optional injected failures."""

    def __init__(self) -> None:
        self.opened: list[tuple[int, int]] = []
        self.live: set[int] = set()
        self.closed: list[int] = []

    def assert_one_open_closed(self) -> None:
        assert len(self.opened) == 1
        assert self.opened[0][0] in self.closed


def watch(monkeypatch, path: Path, *, open_error=None, fstat_error=None, read_error=None, strip_flags=0) -> Watch:
    """Record `os.open`/`os.close` on `path`; make `os.open`, `os.fstat` or `os.read` fail for it if asked."""
    seen = Watch()
    real_fstat, real_read = os.fstat, os.read

    def fake_open(target, flags, *args, **kwargs):
        if os.fspath(target) != str(path):
            return _REAL_OPEN(target, flags, *args, **kwargs)
        if open_error is not None:
            raise open_error
        fd = _REAL_OPEN(target, flags & ~strip_flags, *args, **kwargs)
        seen.opened.append((fd, flags))
        seen.live.add(fd)
        return fd

    def fake_close(fd):
        if fd in seen.live:
            seen.live.discard(fd)
            seen.closed.append(fd)
        return _REAL_CLOSE(fd)

    def fake_fstat(fd):
        if fd in seen.live and fstat_error is not None:
            raise fstat_error
        return real_fstat(fd)

    def fake_read(fd, n):
        if fd in seen.live and read_error is not None:
            raise read_error
        return real_read(fd, n)

    monkeypatch.setattr(os, "open", fake_open)
    monkeypatch.setattr(os, "close", fake_close)
    monkeypatch.setattr(os, "fstat", fake_fstat)
    monkeypatch.setattr(os, "read", fake_read)
    return seen


@pytest.fixture
def fifo(tmp_path):
    """A FIFO at the config path with a writer thread that the kernel pairs with any reader."""
    path = tmp_path / "config.yaml"
    os.mkfifo(path)

    def writer():
        fd = _REAL_OPEN(path, os.O_WRONLY)
        try:
            try:
                _REAL_WRITE(fd, b"strict: true\n")
            except BrokenPipeError:
                pass
        finally:
            _REAL_CLOSE(fd)

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        yield path
    finally:
        # Releases the writer if the code under test never opened a reader.
        reader = _REAL_OPEN(path, os.O_RDONLY | os.O_NONBLOCK)
        thread.join()
        _REAL_CLOSE(reader)


@pytest.mark.posix
def test_directory_in_place_of_file(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.mkdir()
    seen = watch(monkeypatch, path)
    assert_error(path, None, NOT_REGULAR)
    seen.assert_one_open_closed()


@pytest.mark.posix
def test_fifo_with_a_writer_is_rejected_and_its_descriptor_closed(fifo, monkeypatch):
    seen = watch(monkeypatch, fifo)
    assert_error(fifo, None, NOT_REGULAR)
    seen.assert_one_open_closed()


@pytest.mark.posix
def test_fifo_without_a_writer_does_not_block_the_load(tmp_path):
    path = tmp_path / "config.yaml"
    os.mkfifo(path)
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from space.config import ConfigError, load_config\n"
        "try:\n"
        "    load_config(Path(sys.argv[1]))\n"
        "except ConfigError as e:\n"
        "    print(e.reason)\n"
    )
    try:
        # The timeout is a failure bound for a hung child, not a synchronisation point.
        result = subprocess.run([sys.executable, "-c", code, str(path)],
                                capture_output=True,
                                text=True,
                                check=False,
                                timeout=60)
    except subprocess.TimeoutExpired:
        pytest.fail("load_config blocked on a FIFO with no writer")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == NOT_REGULAR


@pytest.mark.posix
def test_device_is_rejected(monkeypatch):
    path = Path("/dev/null")
    seen = watch(monkeypatch, path)
    assert_error(path, None, NOT_REGULAR)
    seen.assert_one_open_closed()


@pytest.mark.posix
def test_not_a_directory_parent(tmp_path):
    parent = tmp_path / "file"
    parent.write_text("x", encoding="utf-8")
    error = rejected(parent / "config.yaml")
    assert error.key_path is None


def test_successful_load_closes_its_descriptor(tmp_path, monkeypatch):
    path = write(tmp_path, "strict: true\n")
    seen = watch(monkeypatch, path)
    assert load_config(path).strict is True
    seen.assert_one_open_closed()


def test_file_larger_than_one_read_is_read_whole(tmp_path):
    path = write(tmp_path, "# padding\n" * 20000 + "strict: true\n")
    assert load_config(path).strict is True


@pytest.mark.posix
@pytest.mark.parametrize("flag", ["O_NONBLOCK", "O_NOCTTY"])
def test_open_flags(tmp_path, monkeypatch, flag):
    assert hasattr(os, flag), f"os.{flag} is missing on this platform"
    path = write(tmp_path, "strict: true\n")
    seen = watch(monkeypatch, path)
    load_config(path)
    assert seen.opened[0][1] & getattr(os, flag) == getattr(os, flag)
    assert seen.opened[0][1] & os.O_ACCMODE == os.O_RDONLY


def test_open_passes_o_binary_where_defined(tmp_path, monkeypatch):
    fake_bit = 1 << 30  # stands in for O_BINARY, which POSIX lacks; the recorder strips it before the real open
    monkeypatch.setattr(os, "O_BINARY", fake_bit, raising=False)
    path = write(tmp_path, "strict: true\n")
    seen = watch(monkeypatch, path, strip_flags=fake_bit)
    load_config(path)
    assert seen.opened[0][1] & fake_bit


@pytest.mark.parametrize("stage", ["fstat_error", "read_error"])
def test_fstat_and_read_failures_close_the_descriptor(tmp_path, monkeypatch, stage):
    path = write(tmp_path, "strict: true\n")
    seen = watch(monkeypatch, path, **{stage: OSError(errno.EIO, os.strerror(errno.EIO))})
    assert_error(path, None, os.strerror(errno.EIO))
    seen.assert_one_open_closed()


@pytest.mark.parametrize("stage", ["fstat_error", "read_error"])
def test_enoent_after_a_successful_open_is_an_error(tmp_path, monkeypatch, stage):
    path = write(tmp_path, "strict: true\n")
    failure = FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT))
    seen = watch(monkeypatch, path, **{stage: failure})
    assert_error(path, None, "No such file or directory")
    seen.assert_one_open_closed()


@pytest.fixture
def short_dir():
    with tempfile.TemporaryDirectory(dir="/tmp") as name:  # AF_UNIX paths are length-limited
        yield Path(name)


@pytest.mark.posix
def test_unix_socket_is_not_a_regular_file(short_dir):
    path = short_dir / "c.sock"
    with socket.socket(socket.AF_UNIX) as sock:
        sock.bind(str(path))
        assert_error(path, None, NOT_REGULAR)


def test_permission_denied_on_a_regular_file_keeps_its_reason(tmp_path, monkeypatch):
    path = write(tmp_path, "strict: true\n")
    watch(monkeypatch, path, open_error=PermissionError(errno.EACCES, "Permission denied", str(path)))
    assert_error(path, None, "Permission denied")


def test_permission_denied(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    watch(monkeypatch, path, open_error=PermissionError(errno.EACCES, "Permission denied", str(path)))
    assert_error(path, None, "Permission denied")


def test_oserror_without_errno_uses_class_name(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    watch(monkeypatch, path, open_error=OSError("boom"))
    assert_error(path, None, "OSError")


def test_oserror_without_strerror_uses_errno(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    failure = OSError(errno.EIO, "x")
    failure.strerror = None
    watch(monkeypatch, path, open_error=failure)
    assert_error(path, None, os.strerror(errno.EIO))


@pytest.mark.posix
def test_surrogate_path_message_is_escaped_and_encodable(tmp_path, monkeypatch):
    path = tmp_path / ("config" + os.fsdecode(b"\xff") + ".yaml")
    watch(monkeypatch, path, open_error=PermissionError(errno.EACCES, "Permission denied", str(path)))
    error = assert_error(path, None, "Permission denied")
    assert str(error).isascii()
    str(error).encode("utf-8")


@pytest.mark.posix
def test_dangling_link_at_the_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.symlink_to(tmp_path / "gone.yaml")
    assert_error(path, None, f"dangling symbolic link {json.dumps(str(path), ensure_ascii=True)}")


@pytest.mark.posix
def test_dangling_link_at_a_parent(tmp_path):
    link = tmp_path / "space"
    link.symlink_to(tmp_path / "gone")
    path = link / "config.yaml"
    assert_error(path, None, f"dangling symbolic link {json.dumps(str(link), ensure_ascii=True)}")


@pytest.mark.posix
def test_dangling_link_is_not_logged_as_missing(tmp_path, caplog):
    path = tmp_path / "config.yaml"
    path.symlink_to(tmp_path / "gone.yaml")
    caplog.set_level(logging.DEBUG, logger="space.config")
    with pytest.raises(ConfigError):
        load_config(path)
    assert "missing" not in "\n".join(r.getMessage() for r in caplog.records)


def _fail_first_open(monkeypatch, before_raising):
    """Make the first `os.open` run `before_raising()` and then fail with ENOENT, as if it had lost a race."""
    real_open = os.open
    calls = []

    def fake_open(path, flags, *args, **kwargs):
        calls.append(path)
        if len(calls) == 1:
            before_raising()
            raise FileNotFoundError(errno.ENOENT, "No such file or directory")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", fake_open)
    return calls


@pytest.mark.posix
def test_file_that_appears_after_the_failed_open_is_read(tmp_path, monkeypatch):
    # A dangling link whose target appears before the dangling-link check looks neither dangling nor missing.
    path = tmp_path / "config.yaml"
    target = tmp_path / "target.yaml"
    path.symlink_to(target)

    def create_target():
        target.write_text("strict: true\n", encoding="utf-8")

    calls = _fail_first_open(monkeypatch, create_target)
    assert load_config(path).strict is True
    assert len(calls) == 2


@pytest.mark.posix
def test_link_created_after_the_failed_open_is_reported_dangling(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    _fail_first_open(monkeypatch, lambda: path.symlink_to(tmp_path / "gone.yaml"))
    assert_error(path, None, f"dangling symbolic link {json.dumps(str(path), ensure_ascii=True)}")


def test_contradictory_missing_file_is_settled_by_one_reopen_then_fails_closed(tmp_path, monkeypatch):
    # The file exists, yet every open says ENOENT: one more open is made, and its failure is reported.
    path = write(tmp_path, "strict: true\n")
    calls = []

    def always_missing(target, flags, *args, **kwargs):
        calls.append(target)
        raise FileNotFoundError(errno.ENOENT, "No such file or directory")

    monkeypatch.setattr(os, "open", always_missing)
    error = assert_error(path, None, "No such file or directory")
    assert isinstance(error.__cause__, FileNotFoundError)
    assert len(calls) == 2


@pytest.mark.parametrize("name", ["a\0b", "\ud800"], ids=["nul", "lone-surrogate"])
def test_unusable_path_is_a_config_error(tmp_path, name):
    path = tmp_path / name
    error = assert_error(path, None, "invalid path")
    assert isinstance(error.__cause__, ValueError)


@pytest.fixture
def unprivileged():
    assert os.geteuid() != 0, "permission tests are meaningless as root: root ignores file modes"


@pytest.mark.posix
def test_unreadable_file_reports_the_real_permission_error(tmp_path, unprivileged):
    path = write(tmp_path, "strict: true\n")
    path.chmod(0o000)
    try:
        assert_error(path, None, os.strerror(errno.EACCES))
    finally:
        path.chmod(0o600)


@pytest.mark.posix
def test_unreadable_parent_reports_the_real_permission_error(tmp_path, unprivileged):
    directory = tmp_path / "space"
    directory.mkdir()
    path = write(directory, "strict: true\n")
    directory.chmod(0o000)
    try:
        assert_error(path, None, os.strerror(errno.EACCES))
    finally:
        directory.chmod(0o700)
