"""Loading the config file into a Config."""

import json
import logging
from collections.abc import Mapping
from pathlib import Path

from space.config import location
from space.config.document import parse_document
from space.config.errors import ConfigError, ConfigValueError
from space.config.keys import KNOWN_KEYS, SETTINGS, top_segment
from space.config.model import Config
from space.config.reading import read_config_file

logger = logging.getLogger("space.config")


def _config_from(path: Path, data: Mapping[object, object]) -> Config:
    for key in data:
        if not isinstance(key, str) or key not in KNOWN_KEYS:
            raise ConfigError(path, top_segment(key), "unknown key")
    for key, value in data.items():
        if value is None:
            raise ConfigError(path, top_segment(key), "null is not allowed; leave the key out to leave it unset")
    kwargs = {field: data[key] for key, field in SETTINGS.items() if key in data}
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
    data = parse_document(path, raw)
    if data is None:
        logger.debug("config file %s: empty; no settings", json.dumps(str(path), ensure_ascii=True))
        return Config()
    config = _config_from(path, data)
    logger.debug("config file %s: loaded", json.dumps(str(path), ensure_ascii=True))
    return config
