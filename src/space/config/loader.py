"""Loading the config file into a Config."""

import json
import logging
from collections.abc import Mapping
from pathlib import Path

from space.config import location
from space.config.document import _parse
from space.config.errors import ConfigError, ConfigValueError
from space.config.keys import _ENDPOINTS_KEY, _KNOWN_KEYS, _STRICT_KEY, _top_segment
from space.config.model import Config
from space.config.reading import read_config_file

logger = logging.getLogger("space.config")


def _config_from(path: Path, data: Mapping[object, object]) -> Config:
    for key in data:
        if not isinstance(key, str) or key not in _KNOWN_KEYS:
            raise ConfigError(path, _top_segment(key), "unknown key")
    for key, value in data.items():
        if value is None:
            raise ConfigError(path, _top_segment(key), "null is not allowed; leave the key out to leave it unset")
    kwargs: dict[str, object] = {}
    if _STRICT_KEY in data:
        kwargs["strict"] = data[_STRICT_KEY]
    if _ENDPOINTS_KEY in data:
        kwargs["trusted_endpoint_overrides"] = data[_ENDPOINTS_KEY]
    try:
        return Config(**kwargs, source=path)  # ty: ignore[invalid-argument-type]  # values are validated by Config
    except ConfigValueError as exc:
        raise ConfigError(path, exc.key_path, exc.reason) from exc


def load_config(path: Path | None = None) -> Config:
    """Load the config file; `path` defaults to the user config file. A missing or empty file means no settings."""
    if path is None:
        path = location.config_path()
        if path is None:
            return Config()
    raw = read_config_file(path)
    if raw is None:
        return Config()
    data = _parse(path, raw)
    if data is None:
        logger.debug("config file %s: empty; no settings", json.dumps(str(path), ensure_ascii=True))
        return Config()
    if not isinstance(data, Mapping):
        raise ConfigError(path, None, f"expected a mapping at the top level, got {type(data).__name__}")
    config = _config_from(path, data)
    logger.debug("config file %s: loaded", json.dumps(str(path), ensure_ascii=True))
    return config
