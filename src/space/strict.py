"""Strict mode settings: `SPACE_STRICT` parsing and the precedence of flag, env and config."""

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from space.config import Config, config_path, load_config
from space.models.enums import set_strict

logger = logging.getLogger("space.strict")

_ENV = "SPACE_STRICT"
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


class InvalidStrictSetting(ValueError):
    """`SPACE_STRICT` holds a value that is not one of the accepted booleans."""


class StrictSource(Enum):
    FLAG = "flag"
    ENV = "env"
    CONFIG = "config"
    DEFAULT = "default"


def parse_strict_env(env: Mapping[str, str]) -> bool | None:
    """`SPACE_STRICT` as a bool, or None when unset or empty. Matching is ASCII-only and never strips whitespace."""
    value = env.get(_ENV)
    if value is None:
        return None
    if value == "":
        logger.debug("%s is empty; ignoring it", _ENV)
        return None
    # Look-alikes such as "o\ufb00" (ff ligature) must be rejected, not case-folded
    folded = value.lower() if value.isascii() else None
    if folded in _TRUE:
        return True
    if folded in _FALSE:
        return False
    raise InvalidStrictSetting(
        f"{_ENV}: expected 1, true, yes, on, 0, false, no or off, got {json.dumps(value, ensure_ascii=True)}"
    )


def resolve_strict(cli_flag: bool | None, env: Mapping[str, str],
                   load_config: Callable[[], Config]) -> tuple[bool, StrictSource]:
    """Strict mode and where it came from: the flag, then `SPACE_STRICT`, then the config file, then off.

    The env var is always parsed, so an invalid value raises even when the flag decides. The config is loaded only
    when neither the flag nor the env var decides; its `ConfigError` propagates.
    """
    from_env = parse_strict_env(env)
    if cli_flag is not None:
        return cli_flag, StrictSource.FLAG
    if from_env is not None:
        return from_env, StrictSource.ENV
    config = load_config()
    if config.strict is not None:
        return config.strict, StrictSource.CONFIG
    return False, StrictSource.DEFAULT


@dataclass(frozen=True)
class StrictSetting:
    """Resolved strict mode, where it came from, and the config file that decided it."""

    enabled: bool
    source: StrictSource
    config_file: Path | None = None  # set exactly when source is CONFIG

    def __post_init__(self) -> None:
        assert (self.source is StrictSource.CONFIG) == (self.config_file is not None), self


def apply_strict(cli_flag: bool | None, env: Mapping[str, str]) -> StrictSetting:
    """Resolve strict mode from `cli_flag` and `env`, and switch it on or off.

    `env` alone locates the config file. On a resolution error the switch is left unchanged.
    """
    loaded: list[Config] = []

    def load() -> Config:
        path = config_path(env)
        config = Config() if path is None else load_config(path)
        loaded.append(config)
        return config

    enabled, source = resolve_strict(cli_flag, env, load)
    config_file = loaded[0].source if source is StrictSource.CONFIG else None
    setting = StrictSetting(enabled, source, config_file)
    set_strict(enabled)
    return setting
