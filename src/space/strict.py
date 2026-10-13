"""Strict mode settings: `SPACE_STRICT` parsing and the precedence of flag, env and config."""

import json
import logging
from collections.abc import Callable, Mapping
from enum import Enum

from space.config import Config

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
    # ASCII-only, so look-alikes such as "o\ufb00" (the ff ligature) are rejected rather than folded
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
