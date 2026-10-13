"""Reading the config file from disk."""

import json
import logging
import os
import stat
from pathlib import Path

from space.config.errors import ConfigError

logger = logging.getLogger("space.config")

_CHUNK = 1 << 16


def _os_reason(exc: OSError) -> str:
    # Never str(exc): it adds an "[Errno N]" prefix and repeats the path in repr form.
    if exc.strerror:
        return exc.strerror
    if exc.errno is not None:
        return os.strerror(exc.errno)
    return type(exc).__name__


def _dangling_link(path: Path) -> Path | None:
    """The first of `path` and its parents that is a symbolic link to nothing."""
    for candidate in (path, *path.parents):
        if os.path.lexists(candidate) and not os.path.exists(candidate):
            return candidate
    return None


def _read_all(fd: int) -> bytes:
    chunks = []
    while chunk := os.read(fd, _CHUNK):
        chunks.append(chunk)
    return b"".join(chunks)


def _open_failure(path: Path, exc: OSError) -> ConfigError:
    """A non-regular file that cannot be opened (a socket, a Windows directory) is named as such."""
    try:
        regular = stat.S_ISREG(os.stat(path).st_mode)
    except OSError:
        regular = True  # keep the original reason
    return ConfigError(path, None, _os_reason(exc) if regular else "not a regular file")


def _open(path: Path) -> int | None:
    """The descriptor, or None when nothing exists at the path."""
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0) | getattr(os, "O_BINARY", 0)
    while True:
        try:
            return os.open(path, flags)
        except FileNotFoundError as exc:
            link = _dangling_link(path)
            if link is not None:
                reason = f"dangling symbolic link {json.dumps(str(link), ensure_ascii=True)}"
                raise ConfigError(path, None, reason) from exc
            if os.path.lexists(path):
                continue  # Created (or its link's target appeared) after the open failed: open again.
            logger.debug("config file %s: missing; no settings", json.dumps(str(path), ensure_ascii=True))
            return None
        except OSError as exc:
            raise _open_failure(path, exc) from exc
        except ValueError as exc:  # An embedded NUL, or a lone surrogate (UnicodeEncodeError) that cannot be encoded.
            raise ConfigError(path, None, "invalid path") from exc


def read_config_file(path: Path) -> bytes | None:
    """The file's bytes, or None when it does not exist.

    Opened non-blocking so a FIFO cannot hang the read; anything but a regular file is an error.
    """
    fd = _open(path)
    if fd is None:
        return None
    try:
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ConfigError(path, None, "not a regular file")
            return _read_all(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise ConfigError(path, None, _os_reason(exc)) from exc
