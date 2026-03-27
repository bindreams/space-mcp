"""YAML serialization utility for MCP tool responses."""

from __future__ import annotations

from io import StringIO
from typing import Any

from ruamel.yaml import YAML


def dump_yaml(data: dict[str, Any] | list[dict[str, Any]]) -> str:
    """Serialize a dict/list to block-style YAML, omitting None values."""
    cleaned = _strip_nones(data)
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    yaml.width = 120
    yaml.indent(mapping=2, sequence=4, offset=2)
    stream = StringIO()
    yaml.dump(cleaned, stream)
    return stream.getvalue()


def _strip_nones(obj: Any) -> Any:
    """Recursively remove None dict values and None list elements."""
    if isinstance(obj, dict):
        return {k: _strip_nones(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, (list, tuple)):
        return [_strip_nones(item) for item in obj if item is not None]
    return obj
