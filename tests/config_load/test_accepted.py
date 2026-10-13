"""Files the loader accepts."""

import warnings

import pytest

import space.config
from space.config import Config, ConfigValueError, load_config

from .helpers import JB, UNKNOWN, assert_error, message, rejected, write


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
