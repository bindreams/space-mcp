"""User config file: where it lives, and the settings it holds."""

import io
import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType

from ruamel.yaml import YAML

from space.origins import normalise_origin

logger = logging.getLogger("space.config")

_FILE_NAME = "config.yaml"


def _is_absolute(value: str, windows: bool) -> bool:
    # Not ntpath.isabs: it calls a drive-less rooted `\cfg` absolute on 3.11 and relative on 3.13.
    pure = PureWindowsPath(value) if windows else PurePosixPath(value)
    return bool(value) and pure.is_absolute()


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


DEFAULT_TRUSTED_ENDPOINTS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "https://jetbrains.team": ("https://patronus.labs.jb.gg", ),
})

_ENDPOINTS_KEY = "patronus-trusted-endpoints"


class ConfigValueError(ValueError):
    """A Config field holds an invalid value; `key_path` is the file-level path of the offending setting."""

    def __init__(self, key_path: str, reason: str):
        super().__init__(f"{key_path}: {reason}")
        self.key_path = key_path
        self.reason = reason


def _key_segment(key: object) -> str:
    return json.dumps(key, ensure_ascii=True) if isinstance(key, str) else f"<{type(key).__name__} key>"


def _normalise_endpoints(raw: object) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(raw, Mapping):
        raise ConfigValueError(_ENDPOINTS_KEY, f"expected a mapping, got {type(raw).__name__}")
    result: dict[str, tuple[str, ...]] = {}
    first_spelling: dict[str, str] = {}
    for key, value in raw.items():
        path = f"{_ENDPOINTS_KEY}.{_key_segment(key)}"
        if not isinstance(key, str):
            raise ConfigValueError(path, "key must be a string")
        try:
            issuer = normalise_origin(key)
        except ValueError as exc:
            raise ConfigValueError(path, str(exc)) from exc
        if issuer in result:
            raise ConfigValueError(
                path,
                f"{json.dumps(first_spelling[issuer], ensure_ascii=True)} and {json.dumps(key, ensure_ascii=True)}"
                f" both name {json.dumps(issuer, ensure_ascii=True)}",
            )
        if isinstance(value, str):
            items: list[object] = [value]
            item_paths = [path]
        elif isinstance(value, (list, tuple)):
            items = list(value)
            item_paths = [f"{path}.[{i}]" for i in range(len(items))]
        else:
            raise ConfigValueError(path, f"expected a string or a list of strings, got {type(value).__name__}")
        origins: dict[str, None] = {}
        for item, item_path in zip(items, item_paths, strict=True):
            if not isinstance(item, str):
                raise ConfigValueError(item_path, f"expected a string, got {type(item).__name__}")
            try:
                origins[normalise_origin(item)] = None
            except ValueError as exc:
                raise ConfigValueError(item_path, str(exc)) from exc
        first_spelling[issuer] = key
        result[issuer] = tuple(origins)
    return MappingProxyType(result)


@dataclass(frozen=True)
class Config:
    """Settings from the config file. `trusted_endpoint_overrides` holds overrides only; see `trusted_patronus_origins`."""

    strict: bool | None = None
    trusted_endpoint_overrides: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: MappingProxyType({}))
    source: Path | None = None

    def __post_init__(self) -> None:
        if self.strict is not None and not isinstance(self.strict, bool):
            raise ConfigValueError("strict", f"expected a boolean, got {type(self.strict).__name__}")
        if self.source is not None and not isinstance(self.source, Path):
            raise ConfigValueError("source", f"expected a path, got {type(self.source).__name__}")
        object.__setattr__(self, "trusted_endpoint_overrides", _normalise_endpoints(self.trusted_endpoint_overrides))

    def trusted_patronus_origins(self, issuer: str) -> tuple[str, ...]:
        """Patronus origins trusted for a Space origin: its override, else the default, else none."""
        issuer = normalise_origin(issuer)
        if issuer in self.trusted_endpoint_overrides:
            return self.trusted_endpoint_overrides[issuer]
        return DEFAULT_TRUSTED_ENDPOINTS.get(issuer, ())

    def trust_suggestion(self, issuer: str, origin: str) -> str:
        """YAML for a complete `patronus-trusted-endpoints` key that also trusts `origin` for `issuer`.

        It replaces the file's existing key; it must not be appended to it.
        """
        issuer = normalise_origin(issuer)
        origin = normalise_origin(origin)
        effective = self.trusted_patronus_origins(issuer)
        updated = dict.fromkeys((*effective, origin))
        block = {key: list(value) for key, value in self.trusted_endpoint_overrides.items()}
        block[issuer] = list(updated)
        yaml = YAML(typ="safe", pure=True)
        yaml.default_flow_style = False
        out = io.StringIO()
        yaml.dump({_ENDPOINTS_KEY: block}, out)
        return out.getvalue()
