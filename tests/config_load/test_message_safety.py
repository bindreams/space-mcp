"""Error messages are safe to print."""

import json

from .helpers import MERGE, UNKNOWN, assert_error, message, rejected, write


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
