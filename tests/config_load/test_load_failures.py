"""YAML that cannot be loaded."""

import sys

import pytest
from ruamel.yaml.scanner import ScannerError

from .helpers import assert_error, message, rejected, write


def _int_digits_limit_case() -> str:
    return "strict: " + "1" * 5000 + "\n"


@pytest.mark.parametrize(
    ("content", "cause"),
    [
        ("strict: 2001-13-45\n", ValueError),
        ("strict: !!int abc\n", ValueError),
        ("strict: !!bool maybe\n", KeyError),
        ("strict: " + "[" * 5000 + "]" * 5000 + "\n", RecursionError),
    ],
)
def test_load_failure(tmp_path, content, cause):
    error = rejected(write(tmp_path, content))
    assert error.key_path is None
    assert type(error.__cause__) is cause
    # Constructor ValueErrors, KeyErrors and RecursionErrors carry no mark, so no position is available.
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
