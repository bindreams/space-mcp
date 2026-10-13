"""Errors raised while loading the config file."""

import json
from pathlib import Path


class ConfigError(Exception):
    """The config file cannot be used. `key_path` is None when the problem is not tied to a setting."""

    def __init__(self, path: Path, key_path: str | None, reason: str):
        shown = json.dumps(str(path), ensure_ascii=True)
        super().__init__(f"{shown}: {reason}" if key_path is None else f"{shown}: {key_path}: {reason}")
        self.path = path
        self.key_path = key_path
        self.reason = reason


class ConfigValueError(ValueError):
    """A Config field holds an invalid value; `key_path` is the file-level path of the offending setting."""

    def __init__(self, key_path: str, reason: str):
        super().__init__(f"{key_path}: {reason}")
        self.key_path = key_path
        self.reason = reason
