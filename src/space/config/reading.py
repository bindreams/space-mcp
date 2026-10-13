"""Reading the config file from disk."""

import json
import logging
import os
from pathlib import Path

from space.config.errors import ConfigError

logger = logging.getLogger("space.config")


def _os_reason(exc: OSError) -> str:
    # Never str(exc): it adds an "[Errno N]" prefix and repeats the path in repr form.
    if exc.strerror:
        return exc.strerror
    if exc.errno is not None:
        return os.strerror(exc.errno)
    return type(exc).__name__


def read_config_file(path: Path) -> bytes | None:
    """The file's bytes, or None when it does not exist."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        logger.debug("config file %s: missing; no settings", json.dumps(str(path), ensure_ascii=True))
        return None
    except OSError as exc:
        raise ConfigError(path, None, _os_reason(exc)) from exc
