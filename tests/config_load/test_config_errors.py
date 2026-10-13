"""Values that `Config` rejects."""

import pytest

from space.config import ConfigValueError

from .helpers import assert_error, message, rejected, write


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
