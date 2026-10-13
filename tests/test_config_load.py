"""Tests for loading and validating the user config file."""

import errno
import json
import logging
import os
import re
import sys
from pathlib import Path

import pytest
from ruamel.yaml.constructor import DuplicateKeyError
from ruamel.yaml.reader import ReaderError
from ruamel.yaml.scanner import ScannerError

import space.config
from space.config import Config, ConfigError, ConfigValueError, load_config

JB = "https://jetbrains.team"
MERGE = "merge keys (<<) are not supported"
ORDERED = "ordered-map tags (!!omap, !!pairs) are not supported"
NULL = "null is not allowed; leave the key out to leave it unset"
UNKNOWN = "unknown key"


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


@pytest.mark.parametrize("tag", ["omap", "pairs"])
def test_top_level_ordered_map_gets_the_shape_error(tmp_path, tag):
    error = rejected(write(tmp_path, f"!!{tag} [a: 1]\n"))
    assert error.key_path is None
    assert error.reason.startswith("expected a mapping at the top level, got ")


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
        ("%YAML 1.3\n---\nstrict: true\n", AssertionError),
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
    ("content", "problem", "position"),
    [
        (
            "strict: true\nstrict: false\n",
            'found duplicate key "strict" with value "False" (original value: "True")',
            "line 2, column 1",
        ),
        (
            'patronus-trusted-endpoints:\n  "https://a.example": []\n  "https://a.example": []\n',
            'found duplicate key "https://a.example" with value "[]" (original value: "[]")',
            "line 3, column 3",
        ),
    ],
)
def test_duplicate_key_reports_problem_and_position(tmp_path, content, problem, position):
    error = rejected(write(tmp_path, content))
    assert type(error.__cause__) is DuplicateKeyError
    assert error.reason == f"invalid YAML (DuplicateKeyError): {json.dumps(problem)} at {position}"
    assert str(error) == message(error.path, None, error.reason)


def test_duplicate_huge_int_keys_are_rejected_with_a_value_error(tmp_path):
    # ruamel's DuplicateKeyError message calls str() on the key, which fails for a huge int.
    huge = "0x" + "f" * 3600
    error = rejected(write(tmp_path, f"? {huge}\n: a\n? {huge}\n: b\n"))
    assert type(error.__cause__) is ValueError
    assert error.reason == "invalid YAML (ValueError)"


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


@pytest.mark.posix
def test_directory_in_place_of_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.mkdir()
    error = rejected(path)
    assert error.key_path is None


@pytest.mark.posix
def test_not_a_directory_parent(tmp_path):
    parent = tmp_path / "file"
    parent.write_text("x", encoding="utf-8")
    error = rejected(parent / "config.yaml")
    assert error.key_path is None


def test_oserror_reason_is_strerror(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"

    def read_bytes(self):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    assert_error(path, None, "Permission denied")


def test_oserror_without_errno_uses_class_name(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"

    def read_bytes(self):
        raise OSError("boom")

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    assert_error(path, None, "OSError")


def test_oserror_without_strerror_uses_errno(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    failure = OSError(errno.EIO, "x")
    failure.strerror = None

    def read_bytes(self):
        raise failure

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    assert_error(path, None, os.strerror(errno.EIO))
