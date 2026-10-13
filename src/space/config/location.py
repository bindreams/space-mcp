"""Where the config file lives."""

import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath

logger = logging.getLogger("space.config")

_FILE_NAME = "config.yaml"


def _is_absolute(value: str, windows: bool) -> bool:
    if not windows:
        return bool(value) and PurePosixPath(value).is_absolute()
    # Not `is_absolute()`: it differs across Python 3.11-3.13 for `\cfg`, `\\server`, `//` and `\\?\`.
    pure = PureWindowsPath(value)
    return bool(pure.drive and pure.root)


def _home(env: Mapping[str, str], windows: bool) -> str | None:
    if not windows:
        home = env.get("HOME", "")
        return home if _is_absolute(home, windows) else None
    userprofile = env.get("USERPROFILE", "")
    if _is_absolute(userprofile, windows):
        return userprofile
    drive_path = env.get("HOMEDRIVE", "") + env.get("HOMEPATH", "")
    return drive_path if _is_absolute(drive_path, windows) else None


def config_dir(env: Mapping[str, str] = os.environ, *, windows: bool = os.name == "nt") -> Path | None:
    """Directory holding the config file, or None when no usable base directory exists."""
    xdg = env.get("XDG_CONFIG_HOME")
    if xdg is not None:
        if _is_absolute(xdg, windows):
            result = Path(xdg) / "space"
            logger.debug("config directory: %s", json.dumps(str(result), ensure_ascii=True))
            return result
        logger.debug("ignoring XDG_CONFIG_HOME=%s: not an absolute path", json.dumps(xdg, ensure_ascii=True))

    home = _home(env, windows)
    if home is None:
        logger.debug("no usable home directory; config file not located")
        return None
    result = Path(home) / ".config" / "space"
    logger.debug("config directory: %s", json.dumps(str(result), ensure_ascii=True))
    return result


def config_path(env: Mapping[str, str] = os.environ, *, windows: bool = os.name == "nt") -> Path | None:
    """Path of the config file, or None when no usable base directory exists."""
    directory = config_dir(env, windows=windows)
    return None if directory is None else directory / _FILE_NAME
