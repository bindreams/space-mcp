"""SPACE_STRICT parsing and strict-mode precedence."""

import json
import logging
import os
from pathlib import Path

import pytest

from space.config import Config, ConfigError
from space.models import enums
from space.strict import InvalidStrictSetting, StrictSetting, StrictSource, apply_strict, parse_strict_env, resolve_strict

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


# apply_strict ---------------------------------------------------------------------------------------------------------


def _write_config(base: Path, text: str) -> Path:
    path = base / "space" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class TestApplyStrict:

    @pytest.mark.unrecognised_api_value
    def test_flag_decides(self):
        assert apply_strict(True, {}) == StrictSetting(True, StrictSource.FLAG, None)
        assert enums.is_strict() is True

    def test_env_decides(self):
        assert apply_strict(None, {"SPACE_STRICT": "0"}) == StrictSetting(False, StrictSource.ENV, None)
        assert enums.is_strict() is False

    @pytest.mark.unrecognised_api_value
    def test_config_decides_and_names_its_file(self, tmp_path):
        path = _write_config(tmp_path / "a", "strict: true\n")
        setting = apply_strict(None, {"XDG_CONFIG_HOME": str(tmp_path / "a")})
        assert setting == StrictSetting(True, StrictSource.CONFIG, path)
        assert enums.is_strict() is True

    @pytest.mark.parametrize(
        ("env_value", "config_text", "expected"),
        [
            ("0", "strict: true\n", False),
            pytest.param("1", "strict: false\n", True, marks=pytest.mark.unrecognised_api_value),
        ],
        ids=["env-off", "env-on"],
    )
    def test_env_beats_config(self, tmp_path, env_value, config_text, expected):
        _write_config(tmp_path / "a", config_text)
        env = {"SPACE_STRICT": env_value, "XDG_CONFIG_HOME": str(tmp_path / "a")}
        assert apply_strict(None, env) == StrictSetting(expected, StrictSource.ENV, None)
        assert enums.is_strict() is expected

    def test_location_comes_from_the_given_mapping(self, tmp_path):
        _write_config(Path(os.environ["XDG_CONFIG_HOME"]), "strict: true\n")
        assert apply_strict(None, {}) == StrictSetting(False, StrictSource.DEFAULT, None)
        other = _write_config(tmp_path / "other", "strict: false\n")
        setting = apply_strict(None, {"XDG_CONFIG_HOME": str(tmp_path / "other")})
        assert setting == StrictSetting(False, StrictSource.CONFIG, other)

    def test_config_without_strict_is_default(self, tmp_path):
        _write_config(
            tmp_path / "a",
            'patronus-trusted-endpoints: {"https://jetbrains.team": "https://patronus-staging.labs.jb.gg"}\n'
        )
        setting = apply_strict(None, {"XDG_CONFIG_HOME": str(tmp_path / "a")})
        assert setting == StrictSetting(False, StrictSource.DEFAULT, None)

    @pytest.mark.unrecognised_api_value
    @pytest.mark.parametrize("case", ["bad-env-with-flag", "broken-config"])
    def test_failures_leave_the_switch_alone(self, tmp_path, case):
        if case == "bad-env-with-flag":
            with pytest.raises(InvalidStrictSetting):
                apply_strict(True, {"SPACE_STRICT": "maybe"})
        else:
            _write_config(tmp_path / "a", "strict: maybe\n")
            with pytest.raises(ConfigError):
                apply_strict(None, {"XDG_CONFIG_HOME": str(tmp_path / "a")})
        assert enums.is_strict() is False

    @pytest.mark.parametrize(
        ("source", "config_file"),
        [(StrictSource.FLAG, Path("/x")), (StrictSource.CONFIG, None)],
        ids=["flag-with-file", "config-without-file"],
    )
    def test_setting_invariant(self, source, config_file):
        with pytest.raises(AssertionError):
            StrictSetting(True, source, config_file)
