"""The settings a config file holds, and the default trust."""

import io
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from ruamel.yaml import YAML

from space.config.errors import ConfigValueError
from space.config.keys import _ENDPOINTS_KEY, _key_segment
from space.origins import normalise_origin

DEFAULT_TRUSTED_ENDPOINTS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "https://jetbrains.team": ("https://patronus.labs.jb.gg", ),
})


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
