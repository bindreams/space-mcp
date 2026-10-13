"""Shared constants and helpers for the config loader tests."""

import json
from pathlib import Path

import pytest

from space.config import ConfigError, load_config

JB = "https://jetbrains.team"
MERGE = "merge keys (<<) are not supported"
NON_SCALAR_KEY = "keys must be plain scalars"
ALIAS_KEY = "keys must not be aliases"
VALUE_KEY = "value keys (=) are not supported"
ORDERED = "ordered-map tags (!!omap, !!pairs) are not supported"
NULL = "null is not allowed; leave the key out to leave it unset"
UNKNOWN = "unknown key"
NOT_REGULAR = "not a regular file"


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
