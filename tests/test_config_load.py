"""Tests for loading and validating the user config file."""

import errno
import json
import logging
import os
import re
import socket
import subprocess
import sys
import warnings
import tempfile
import threading
from pathlib import Path

import pytest
from ruamel.yaml.reader import ReaderError
from ruamel.yaml.scanner import ScannerError

import space.config
from space.config import Config, ConfigError, ConfigValueError, load_config

JB = "https://jetbrains.team"
MERGE = "merge keys (<<) are not supported"
ORDERED = "ordered-map tags (!!omap, !!pairs) are not supported"
NULL = "null is not allowed; leave the key out to leave it unset"
UNKNOWN = "unknown key"
NOT_REGULAR = "not a regular file"

# Captured at import, before any test patches `os`; the FIFO writer and teardown use only these.
_REAL_OPEN = os.open
_REAL_CLOSE = os.close
_REAL_WRITE = os.write


def write(tmp_path: Path, content: str | bytes) -> Path:
    path = tmp_path / "config.yaml"
    if isinstance(content, str):
        content = content.encode("utf-8")
    path.write_bytes(content)
    return path


def rejected(path: Path) -> ConfigError:
    with pytest.raises(ConfigError) as info:
        load_config(path)
    assert info.value.path == path
    return info.value


def message(path: Path, key_path: str | None, reason: str) -> str:
    prefix = json.dumps(str(path), ensure_ascii=True)
    return f"{prefix}: {reason}" if key_path is None else f"{prefix}: {key_path}: {reason}"


def assert_error(path: Path, key_path: str | None, reason: str) -> ConfigError:
    error = rejected(path)
    assert error.key_path == key_path
    assert error.reason == reason
    assert str(error) == message(path, key_path, reason)
    return error


# Accepted -------------------------------------------------------------------------------------------------------------


def test_utf8_bom(tmp_path):
    assert load_config(write(tmp_path, b"\xef\xbb\xbfstrict: true\n")).strict is True


def test_utf16_bom(tmp_path):
    assert load_config(write(tmp_path, "strict: true\n".encode("utf-16"))).strict is True


@pytest.mark.parametrize("content", ["", "# only a comment\n", "---\n", "null\n", "~\n", "---\nnull\n"])
def test_no_settings(tmp_path, content):
    path = write(tmp_path, content)
    assert load_config(path) == Config()
    assert load_config(path).source is None


def test_yaml_12_directive(tmp_path):
    assert load_config(write(tmp_path, "%YAML 1.2\n---\nstrict: false\n")).strict is False


@pytest.mark.parametrize(("text", "expected"), [("true", True), ("false", False), ("!!bool yes", True)])
def test_strict(tmp_path, text, expected):
    assert load_config(write(tmp_path, f"strict: {text}\n")).strict is expected


def test_endpoints_list_and_short_form_normalised_and_deduplicated(tmp_path):
    content = (
        "patronus-trusted-endpoints:\n"
        '  "https://JetBrains.team/":\n'
        '    - "https://B.example/"\n'
        '    - "https://a.example"\n'
        '    - "https://b.example"\n'
        '  "https://other.example": "https://P.example:8443/"\n'
        '  "https://none.example": []\n'
    )
    config = load_config(write(tmp_path, content))
    assert dict(config.trusted_endpoint_overrides) == {
        JB: ("https://b.example", "https://a.example"),
        "https://other.example": ("https://p.example:8443", ),
        "https://none.example": (),
    }


def test_empty_endpoints_mapping(tmp_path):
    config = load_config(write(tmp_path, "patronus-trusted-endpoints: {}\n"))
    assert dict(config.trusted_endpoint_overrides) == {}
    assert config.strict is None


def test_anchored_list_reused_by_alias(tmp_path):
    content = (
        "patronus-trusted-endpoints:\n"
        '  "https://a.example": &p ["https://p.example"]\n'
        '  "https://b.example": *p\n'
    )
    config = load_config(write(tmp_path, content))
    assert dict(config.trusted_endpoint_overrides) == {
        "https://a.example": ("https://p.example", ),
        "https://b.example": ("https://p.example", ),
    }


def test_reused_anchor_emits_no_warning(tmp_path):
    path = write(tmp_path, 'strict: &a true\npatronus-trusted-endpoints: &a {"https://x.com": []}  # \u202e evil\n')
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = load_config(path)
    assert [str(w.message) for w in caught] == []
    assert config.strict is True
    assert dict(config.trusted_endpoint_overrides) == {"https://x.com": ()}


def test_quoted_merge_key_is_an_unknown_key(tmp_path):
    assert_error(write(tmp_path, '"<<": 1\n'), '"<<"', UNKNOWN)


def test_quoted_merge_key_under_endpoints_is_an_invalid_origin(tmp_path):
    error = rejected(write(tmp_path, 'patronus-trusted-endpoints:\n  "<<": []\n'))
    assert error.key_path == 'patronus-trusted-endpoints."<<"'
    assert isinstance(error.__cause__, ConfigValueError)
    assert error.reason == error.__cause__.reason
    assert 'origin' in error.reason and '"<<"' in error.reason
    assert str(error) == message(error.path, error.key_path, error.reason)


def test_source_is_set(tmp_path):
    path = write(tmp_path, "strict: true\n")
    assert load_config(path).source == path


def test_default_path_is_config_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    directory = tmp_path / ".config" / "space"
    directory.mkdir(parents=True)
    path = directory / "config.yaml"
    path.write_text("strict: true\n", encoding="utf-8")
    config = load_config()
    assert config.strict is True
    assert config.source == path


def test_no_config_path_gives_default_config(monkeypatch):
    monkeypatch.setattr(space.config.location, "config_path", lambda: None)
    assert load_config() == Config()


def test_missing_file_is_no_settings(tmp_path):
    assert load_config(tmp_path / "absent.yaml") == Config()


# Debug logs -----------------------------------------------------------------------------------------------------------


def _load_logged(path: Path, caplog) -> str:
    caplog.set_level(logging.DEBUG, logger="space.config")
    load_config(path)
    return "\n".join(r.getMessage() for r in caplog.records if r.name == "space.config")


def test_log_missing(tmp_path, caplog):
    path = tmp_path / "absent.yaml"
    text = _load_logged(path, caplog)
    assert json.dumps(str(path), ensure_ascii=True) in text
    assert "missing" in text


@pytest.mark.parametrize("content", ["", "# comment\n"])
def test_log_empty(tmp_path, caplog, content):
    path = write(tmp_path, content)
    text = _load_logged(path, caplog)
    assert json.dumps(str(path), ensure_ascii=True) in text
    assert "empty" in text


def test_log_loaded(tmp_path, caplog):
    path = write(tmp_path, "strict: true\n")
    text = _load_logged(path, caplog)
    assert json.dumps(str(path), ensure_ascii=True) in text
    assert "loaded" in text


# Rejected by the loader -----------------------------------------------------------------------------------------------


def test_unknown_top_level_key(tmp_path):
    assert_error(write(tmp_path, "colour: red\n"), '"colour"', UNKNOWN)


def test_non_str_top_level_key(tmp_path):
    assert_error(write(tmp_path, "1: x\n"), "<int key>", UNKNOWN)


@pytest.mark.parametrize(
    ("content", "type_name"),
    [("- a\n", "list"), ("5\n", "int"), ("hello\n", "str"), ("true\n", "bool")],
)
def test_top_level_must_be_a_mapping(tmp_path, content, type_name):
    path = write(tmp_path, content)
    assert_error(path, None, f"expected a mapping at the top level, got {type_name}")


def test_strict_null(tmp_path):
    assert_error(write(tmp_path, "strict: null\n"), "strict", NULL)
    assert_error(write(tmp_path, "strict:\n"), "strict", NULL)


def test_endpoints_null(tmp_path):
    assert_error(write(tmp_path, "patronus-trusted-endpoints: null\n"), "patronus-trusted-endpoints", NULL)


def test_endpoints_list(tmp_path):
    error = assert_error(
        write(tmp_path, "patronus-trusted-endpoints: [a]\n"), "patronus-trusted-endpoints",
        "expected a mapping, got list"
    )
    assert isinstance(error.__cause__, ConfigValueError)


def test_merge_at_top_level(tmp_path):
    assert_error(write(tmp_path, "base: &b {strict: true}\n<<: *b\n"), None, MERGE)


def test_merge_under_endpoints(tmp_path):
    content = 'patronus-trusted-endpoints:\n  <<: {"https://a.example": []}\n'
    assert_error(write(tmp_path, content), "patronus-trusted-endpoints", MERGE)


def test_merge_in_sequence_item(tmp_path):
    assert_error(write(tmp_path, "items:\n  - a: 1\n  - <<: {}\n"), '"items".[1]', MERGE)


@pytest.mark.parametrize("content", ["1: {<<: {}}\n", "? [1]\n: {<<: {}}\n"])
def test_merge_under_non_str_key(tmp_path, content):
    assert_error(write(tmp_path, content), "<non-str key>", MERGE)


def test_merge_in_nested_mapping(tmp_path):
    assert_error(write(tmp_path, "a:\n  b:\n    <<: {}\n"), '"a"."b"', MERGE)


def test_merge_inside_a_key(tmp_path):
    assert_error(write(tmp_path, "a:\n  ? {<<: {}}\n  : 1\n"), '"a".<non-str key>', MERGE)


def test_merge_in_anchored_mapping_reported_at_first_occurrence(tmp_path):
    content = "b:\n  c: &x\n    <<: {}\nd: *x\n"
    assert_error(write(tmp_path, content), '"b"."c"', MERGE)


def test_first_merge_in_document_order_wins(tmp_path):
    assert_error(write(tmp_path, "a:\n  <<: {}\n<<: {}\n"), '"a"', MERGE)
    assert_error(write(tmp_path, "<<: {}\na:\n  <<: {}\n"), None, MERGE)


def test_recursive_alias_terminates(tmp_path):
    assert_error(write(tmp_path, "a: &x\n  self: *x\n"), '"a"', UNKNOWN)


def test_top_level_sequence_holding_a_merge_gets_the_shape_error(tmp_path):
    assert_error(write(tmp_path, "- <<: {}\n"), None, "expected a mapping at the top level, got list")


@pytest.mark.parametrize("tag", ["omap", "pairs"])
@pytest.mark.parametrize(
    ("template", "key_path"),
    [
        ("strict: !!{tag} [a: 1]\n", "strict"),
        ("strict: !!{tag} [a: 1, a: 2]\n", "strict"),
        ("patronus-trusted-endpoints: !!{tag} []\n", "patronus-trusted-endpoints"),
        (
            'patronus-trusted-endpoints: !!{tag} [{{"https://jetbrains.team": []}}, '
            '{{"https://jetbrains.team": ["https://x.example"]}}]\n',
            "patronus-trusted-endpoints",
        ),
        ("a:\n  b: !!{tag} [c: 1]\n", '"a"."b"'),
    ],
)
def test_ordered_map_tags_rejected(tmp_path, tag, template, key_path):
    assert_error(write(tmp_path, template.format(tag=tag)), key_path, ORDERED)


@pytest.mark.parametrize(
    "content",
    [
        "!!omap [strict: true]\n",
        "!!omap {strict: true}\n",
        "!!omap [strict: true, strict: false]\n",
        "!!pairs [strict: true]\n",
    ],
)
def test_top_level_ordered_map_is_rejected(tmp_path, content):
    path = write(tmp_path, content)
    error = assert_error(path, None, ORDERED)
    assert str(error) == message(path, None, ORDERED)


@pytest.mark.parametrize("content", ["!!set {}\n", "!!set {strict: null}\n", "!!set\n? strict\n"])
def test_top_level_set_gets_the_shape_error(tmp_path, content):
    assert_error(write(tmp_path, content), None, "expected a mapping at the top level, got set")


@pytest.mark.parametrize(
    ("content", "type_name"),
    [
        ("- !!int abc\n", "list"),
        ("- {a: 1, a: 2}\n", "list"),
        ("- !foo x\n", "list"),
        ("!!set {<<: {}}\n", "set"),
        ("!!set {a, a}\n", "set"),
    ],
)
def test_top_level_shape_is_checked_before_constructing(tmp_path, content, type_name):
    assert_error(write(tmp_path, content), None, f"expected a mapping at the top level, got {type_name}")


def test_ordered_maps_rejected_under_python_dash_o(tmp_path):
    # pytest strips asserts under -O, so only a subprocess proves ruamel's assert-based checks are not relied on.
    contents = [
        "strict: !!omap [a: 1, a: 2]\n",
        "strict: !!pairs [a: 1, a: 2]\n",
        'patronus-trusted-endpoints: !!omap [{"https://x.com": []}, {"https://x.com": ["https://p.com"]}]\n',
        'patronus-trusted-endpoints: !!pairs [{"https://x.com": []}, {"https://x.com": ["https://p.com"]}]\n',
    ]
    paths = []
    for i, content in enumerate(contents):
        (tmp_path / str(i)).mkdir()
        paths.append(str(write(tmp_path / str(i), content)))
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from space.config import ConfigError, load_config\n"
        "assert not __debug__\n"
        "for p in sys.argv[1:]:\n"
        "    try:\n"
        "        load_config(Path(p))\n"
        "    except ConfigError as e:\n"
        "        print(e.key_path, e.reason, sep='|')\n"
        "    else:\n"
        "        print('LOADED')\n"
    )
    result = subprocess.run([sys.executable, "-O", "-c", code, *paths], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f"strict|{ORDERED}"] * 2 + [f"patronus-trusted-endpoints|{ORDERED}"] * 2


def test_yaml_11_rejected(tmp_path):
    assert_error(write(tmp_path, "%YAML 1.1\n---\nstrict: true\n"), None, "unsupported YAML version 1.1; use 1.2")


def test_parser_not_reused_after_yaml_11(tmp_path):
    rejected(write(tmp_path, "%YAML 1.1\n---\nstrict: true\n"))
    assert load_config(write(tmp_path, "strict: true\n")).strict is True


# Rejected by Config ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("value", "type_name"), [("yes", "str"), ("1", "int"), ("0", "int"), ('"true"', "str"),
                                                  ('"false"', "str")])
def test_strict_wrong_type(tmp_path, value, type_name):
    error = assert_error(write(tmp_path, f"strict: {value}\n"), "strict", f"expected a boolean, got {type_name}")
    assert isinstance(error.__cause__, ConfigValueError)


@pytest.mark.parametrize(
    ("body", "key_path"),
    [
        ('"https://a.example": null', 'patronus-trusted-endpoints."https://a.example"'),
        ('"https://a.example": 5', 'patronus-trusted-endpoints."https://a.example"'),
        ('"https://a.example": {x: y}', 'patronus-trusted-endpoints."https://a.example"'),
        ("1: []", "patronus-trusted-endpoints.<int key>"),
        ("true: []", "patronus-trusted-endpoints.<bool key>"),
        ("null: []", "patronus-trusted-endpoints.<NoneType key>"),
        ("2001-01-01: []", "patronus-trusted-endpoints.<date key>"),
        ("? [a, b]\n  : []", "patronus-trusted-endpoints.<tuple key>"),
        ('"https://a.example": [null]', 'patronus-trusted-endpoints."https://a.example".[0]'),
        ('"https://a.example": ["https://p.example", 3]', 'patronus-trusted-endpoints."https://a.example".[1]'),
        ('"": []', 'patronus-trusted-endpoints.""'),
        ('"https://a.example": [""]', 'patronus-trusted-endpoints."https://a.example".[0]'),
        ('"https://a.example": ""', 'patronus-trusted-endpoints."https://a.example"'),
        ('"http://a.example": []', 'patronus-trusted-endpoints."http://a.example"'),
        ('"https://a.example": ["not an origin"]', 'patronus-trusted-endpoints."https://a.example".[0]'),
    ],
)
def test_config_value_errors(tmp_path, body, key_path):
    error = rejected(write(tmp_path, f"patronus-trusted-endpoints:\n  {body}\n"))
    assert error.key_path == key_path
    assert isinstance(error.__cause__, ConfigValueError)
    assert error.__cause__.key_path == key_path
    assert error.reason == error.__cause__.reason
    assert str(error) == message(error.path, key_path, error.reason)


def test_keys_normalising_equal_name_both_spellings(tmp_path):
    content = 'patronus-trusted-endpoints:\n  "https://A.example": []\n  "https://a.example/": []\n'
    error = rejected(write(tmp_path, content))
    assert error.key_path == 'patronus-trusted-endpoints."https://a.example/"'
    assert '"https://A.example"' in error.reason
    assert '"https://a.example/"' in error.reason
    assert isinstance(error.__cause__, ConfigValueError)
    assert error.reason == error.__cause__.reason
    assert str(error) == message(error.path, error.key_path, error.reason)


# Load failures --------------------------------------------------------------------------------------------------------


def _int_digits_limit_case() -> str:
    return "strict: " + "1" * 5000 + "\n"


@pytest.mark.parametrize(
    ("content", "cause"),
    [
        # ruamel guards the version with an `assert`; under `python -O` the failure is a KeyError instead.
        ("%YAML 1.3\n---\nstrict: true\n", AssertionError if __debug__ else KeyError),
        ("strict: 2001-13-45\n", ValueError),
        ("strict: !!int abc\n", ValueError),
        ("strict: {? [[a]]: x}\n", TypeError),
        ("strict: !!bool maybe\n", KeyError),
        ("strict: " + "[" * 5000 + "]" * 5000 + "\n", RecursionError),
        (b"strict: \xc3\x28\n", ReaderError),
    ],
)
def test_load_failure(tmp_path, content, cause):
    error = rejected(write(tmp_path, content))
    assert error.key_path is None
    assert type(error.__cause__) is cause
    assert error.reason == f"invalid YAML ({cause.__name__})"
    assert str(error) == message(error.path, None, error.reason)


def test_load_failure_int_digit_limit(tmp_path):
    path = write(tmp_path, _int_digits_limit_case())
    previous = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(4300)
    try:
        error = rejected(path)
    finally:
        sys.set_int_max_str_digits(previous)
    assert type(error.__cause__) is ValueError
    assert error.reason == "invalid YAML (ValueError)"


@pytest.mark.parametrize(
    ("content", "key_path", "reason"),
    [
        ("strict: true\nstrict: false\n", None, 'duplicate key "strict" at line 2, column 1'),
        (
            'patronus-trusted-endpoints:\n  "https://a.example": []\n  "https://a.example": []\n',
            "patronus-trusted-endpoints",
            'duplicate key "https://a.example" at line 3, column 3',
        ),
        ("a:\n  b:\n    c: 1\n    c: 2\n", '"a"."b"', 'duplicate key "c" at line 4, column 5'),
        ("strict: !!set {a, a}\n", "strict", 'duplicate key "a" at line 1, column 19'),
    ],
)
def test_duplicate_key_reports_key_and_position(tmp_path, content, key_path, reason):
    error = assert_error(write(tmp_path, content), key_path, reason)
    assert error.__cause__ is None


def test_duplicate_huge_int_keys_are_named_by_type(tmp_path):
    huge = "0x" + "f" * 3600
    assert_error(
        write(tmp_path, f"? {huge}\n: a\n? {huge}\n: b\n"), None, "duplicate key <non-str key> at line 3, column 3"
    )


def test_duplicate_key_never_formats_values(tmp_path):
    # ruamel's own message str()s the values; through anchors that grows exponentially (8 levels: tens of MB).
    lines = ["l0: &l0 [" + ", ".join(["x"] * 10) + "]"]
    lines += [f"l{i}: &l{i} [" + ", ".join([f"*l{i - 1}"] * 10) + "]" for i in range(1, 8)]
    lines += ['patronus-trusted-endpoints: {"https://x.com": [], "https://x.com": *l7}']
    error = rejected(write(tmp_path, "\n".join(lines) + "\n"))
    assert error.key_path == "patronus-trusted-endpoints"
    assert error.reason == 'duplicate key "https://x.com" at line 9, column 51'
    assert len(str(error)) < 500


def test_load_failure_never_embeds_unsafe_source_text(tmp_path):
    error = rejected(write(tmp_path, "strict: \u202e: x\n"))
    assert type(error.__cause__) is ScannerError
    assert error.reason == 'invalid YAML (ScannerError): "mapping values are not allowed here" at line 1, column 10'
    assert "\u202e" in str(error.__cause__)
    assert "\u202e" not in str(error)
    assert str(error).isascii()


# Message safety -------------------------------------------------------------------------------------------------------


def test_issuer_key_with_control_characters_is_json_escaped(tmp_path):
    content = 'patronus-trusted-endpoints:\n  "a\\nb\\x1b[31m": []\n'
    error = rejected(write(tmp_path, content))
    assert "\n" not in str(error)
    assert "\x1b" not in str(error)
    assert error.key_path == 'patronus-trusted-endpoints."a\\nb\\u001b[31m"'
    assert str(error) == message(error.path, error.key_path, error.reason)
    assert str(error).isascii()


def test_unknown_key_with_escape_is_json_escaped(tmp_path):
    error = assert_error(write(tmp_path, '"\\x1b[31m": 1\n'), json.dumps("\x1b[31m"), UNKNOWN)
    assert "\x1b" not in str(error)


def test_merge_under_key_with_escape_has_json_escaped_key_path(tmp_path):
    error = assert_error(write(tmp_path, '"\\x1b[31m":\n  <<: {}\n'), json.dumps("\x1b[31m"), MERGE)
    assert "\x1b" not in str(error)


def test_huge_int_key_named_by_type(tmp_path):
    assert_error(write(tmp_path, "? 0x" + "f" * 3600 + "\n: x\n"), "<int key>", UNKNOWN)


def test_non_ascii_path_is_json_escaped(tmp_path):
    path = tmp_path / "\u202econfig.yaml"
    path.write_text("colour: red\n", encoding="utf-8")
    error = rejected(path)
    assert str(error).isascii()
    assert "\u202e" not in str(error)


# File system ----------------------------------------------------------------------------------------------------------


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
def test_fifo_is_rejected_without_blocking(fifo, monkeypatch):
    seen = watch(monkeypatch, fifo)
    assert_error(fifo, None, NOT_REGULAR)
    seen.assert_one_open_closed()


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


@pytest.mark.parametrize("flag", ["O_NONBLOCK", "O_NOCTTY"])
def test_open_flags(tmp_path, monkeypatch, flag):
    path = write(tmp_path, "strict: true\n")
    seen = watch(monkeypatch, path)
    load_config(path)
    assert seen.opened[0][1] & getattr(os, flag, 0) == getattr(os, flag, 0)
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


@pytest.mark.parametrize("name", ["a\0b", "\ud800"], ids=["nul", "lone-surrogate"])
def test_unusable_path_is_a_config_error(tmp_path, name):
    path = tmp_path / name
    error = assert_error(path, None, "invalid path")
    assert isinstance(error.__cause__, ValueError)
