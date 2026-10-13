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
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

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

_STRICT_KEY = "strict"
_ENDPOINTS_KEY = "patronus-trusted-endpoints"
_KNOWN_KEYS = (_STRICT_KEY, _ENDPOINTS_KEY)
_STR_TAG = "tag:yaml.org,2002:str"
_MERGE_TAG = "tag:yaml.org,2002:merge"


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


def _key_segment(key: object) -> str:
    return json.dumps(key, ensure_ascii=True) if isinstance(key, str) else f"<{type(key).__name__} key>"


def _top_segment(key: object) -> str:
    """First segment of a key path: the known setting names appear bare."""
    return key if isinstance(key, str) and key in _KNOWN_KEYS else _key_segment(key)


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

    # Explicit: the generated hash would fail on the mapping field with an obscure message.
    __hash__ = None

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


def _os_reason(exc: OSError) -> str:
    # Never str(exc): it adds an "[Errno N]" prefix and repeats the path in repr form.
    if exc.strerror:
        return exc.strerror
    if exc.errno is not None:
        return os.strerror(exc.errno)
    return type(exc).__name__


def _load_failure_reason(exc: Exception) -> str:
    # Never str(exc): ruamel quotes source lines, which may carry unsafe printable characters.
    reason = f"invalid YAML ({type(exc).__name__})"
    problem = getattr(exc, "problem", None)
    if problem:
        reason += f": {json.dumps(str(problem), ensure_ascii=True)}"
    mark = getattr(exc, "problem_mark", None)
    if mark is not None:
        reason += f" at line {mark.line + 1}, column {mark.column + 1}"
    return reason


def _parent_segment(key_node: Node, top: bool) -> str:
    if isinstance(key_node, ScalarNode) and key_node.tag == _STR_TAG:
        return _top_segment(key_node.value) if top else _key_segment(key_node.value)
    return "<non-str key>"


def _find_merge_key(root: Node) -> tuple[str | None] | None:
    """Key path (in a 1-tuple) of the first `<<` in document order, or None when there is none."""
    visited: set[int] = set()
    # Entries: (node, key path of the node, key path of the mapping holding the node when it is a key).
    stack: list[tuple[Node, tuple[str, ...], tuple[str, ...] | None]] = [(root, (), None)]
    while stack:
        node, path, holder = stack.pop()
        if holder is not None and node.tag == _MERGE_TAG:
            return (".".join(holder) or None, )
        if id(node) in visited:
            continue
        visited.add(id(node))
        children: list[tuple[Node, tuple[str, ...], tuple[str, ...] | None]] = []
        if isinstance(node, MappingNode):
            for key_node, value_node in node.value:
                child_path = (*path, _parent_segment(key_node, top=not path))
                children.append((key_node, child_path, path))
                children.append((value_node, child_path, None))
        elif isinstance(node, SequenceNode):
            children.extend((item, (*path, f"[{i}]"), None) for i, item in enumerate(node.value))
        stack.extend(reversed(children))
    return None


def _parse(path: Path, data: bytes) -> object:
    yaml = YAML(typ="safe", pure=True)  # Fresh per load: a reused instance keeps a `%YAML 1.1` directive's version.
    try:
        node = yaml.compose(data)
        if yaml.version not in (None, (1, 2)):
            major, minor = yaml.version
            raise ConfigError(path, None, f"unsupported YAML version {major}.{minor}; use 1.2")
        if node is None:
            return None
        # ruamel applies YAML 1.1's `<<` even in 1.2 mode, silently overriding or dropping entries.
        merge = _find_merge_key(node)
        if merge is not None:
            raise ConfigError(path, merge[0], "merge keys (<<) are not supported")
        return yaml.constructor.construct_document(node)
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError(path, None, _load_failure_reason(exc)) from exc


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
        path = config_path()
        if path is None:
            return Config()
    shown = json.dumps(str(path), ensure_ascii=True)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        logger.debug("config file %s: missing; no settings", shown)
        return Config()
    except OSError as exc:
        raise ConfigError(path, None, _os_reason(exc)) from exc
    data = _parse(path, raw)
    if data is None:
        logger.debug("config file %s: empty; no settings", shown)
        return Config()
    if not isinstance(data, Mapping):
        raise ConfigError(path, None, f"expected a mapping at the top level, got {type(data).__name__}")
    config = _config_from(path, data)
    logger.debug("config file %s: loaded", shown)
    return config
