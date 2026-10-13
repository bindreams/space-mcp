"""SPACE_STRICT parsing and strict-mode precedence."""

import json
import logging
from pathlib import Path

import pytest

from space.config import Config, ConfigError
from space.strict import InvalidStrictSetting, StrictSource, parse_strict_env, resolve_strict

_EXPECTED = "expected 1, true, yes, on, 0, false, no or off"


def _invalid_message(value: str) -> str:
    return f"SPACE_STRICT: {_EXPECTED}, got {json.dumps(value, ensure_ascii=True)}"


class _Loader:
    """A `load_config` spy; `broken` loaders raise ConfigError, so a call where none is allowed fails loudly."""

    def __init__(self, config: Config | None = None, broken: bool = False):
        self.config = config
        self.broken = broken
        self.calls = 0

    def __call__(self) -> Config:
        self.calls += 1
        if self.broken:
            raise ConfigError(Path("/cfg/space/config.yaml"), None, "broken on purpose")
        assert self.config is not None
        return self.config


class TestParseStrictEnv:

    def test_unset_is_none(self):
        assert parse_strict_env({}) is None

    def test_empty_is_none_and_logged(self, caplog):
        caplog.set_level(logging.DEBUG, logger="space.strict")
        assert parse_strict_env({"SPACE_STRICT": ""}) is None
        assert [(r.name, r.levelno, r.getMessage())
                for r in caplog.records] == [("space.strict", logging.DEBUG, "SPACE_STRICT is empty; ignoring it")]

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "True", "yes", "YES", "on", "On"])
    def test_true_values(self, value):
        assert parse_strict_env({"SPACE_STRICT": value}) is True

    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "No", "off", "OFF"])
    def test_false_values(self, value):
        assert parse_strict_env({"SPACE_STRICT": value}) is False

    @pytest.mark.parametrize(
        "value", ["2", "enable", "tru", " 1 ", "1 ", " ", "1\n", "\x1b[31m", "oﬀ", "yeſ", "１", "é"]
    )
    def test_invalid_values_raise(self, value):
        with pytest.raises(InvalidStrictSetting) as info:
            parse_strict_env({"SPACE_STRICT": value})
        assert str(info.value) == _invalid_message(value)


class TestResolveStrict:

    @pytest.mark.parametrize(
        ("flag", "env", "config", "expected", "loads"),
        [
            (True, {}, None, (True, StrictSource.FLAG), 0),
            (False, {"SPACE_STRICT": "true"}, None, (False, StrictSource.FLAG), 0),
            (True, {}, Config(strict=False), (True, StrictSource.FLAG), 0),
            (None, {"SPACE_STRICT": "1"}, None, (True, StrictSource.ENV), 0),
            (None, {"SPACE_STRICT": "false"}, Config(strict=True), (False, StrictSource.ENV), 0),
            (None, {"SPACE_STRICT": ""}, Config(strict=True), (True, StrictSource.CONFIG), 1),
            (None, {}, Config(strict=False), (False, StrictSource.CONFIG), 1),
            (None, {}, Config(), (False, StrictSource.DEFAULT), 1),
        ],
        ids=[
            "flag-on", "flag-off-beats-env", "flag-on-beats-config", "env-on", "env-off-beats-config",
            "empty-env-falls-to-config", "config-off", "no-key-default"
        ],
    )
    def test_resolve_strict_precedence(self, flag, env, config, expected, loads):
        loader = _Loader(config, broken=loads == 0)
        assert resolve_strict(flag, env, loader) == expected
        assert loader.calls == loads

    @pytest.mark.parametrize("flag", [True, False, None])
    def test_resolve_strict_invalid_env_raises_even_with_flag(self, flag):
        loader = _Loader(broken=True)
        with pytest.raises(InvalidStrictSetting):
            resolve_strict(flag, {"SPACE_STRICT": "maybe"}, loader)
        assert loader.calls == 0

    def test_resolve_strict_propagates_config_error(self):
        loader = _Loader(broken=True)
        with pytest.raises(ConfigError, match="broken on purpose"):
            resolve_strict(None, {}, loader)
        assert loader.calls == 1
