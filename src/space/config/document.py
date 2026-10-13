"""Parsing the YAML document and rejecting constructs the config file does not support."""

import json
from collections.abc import Mapping
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from space.config.errors import ConfigError
from space.config.keys import _key_segment, _top_segment

_STR_TAG = "tag:yaml.org,2002:str"
_MERGE_TAG = "tag:yaml.org,2002:merge"
_ORDERED_TAGS = ("tag:yaml.org,2002:omap", "tag:yaml.org,2002:pairs")
_MERGE_REASON = "merge keys (<<) are not supported"
_ORDERED_REASON = "ordered-map tags (!!omap, !!pairs) are not supported"


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


def _reject_unsupported(path: Path, root: Node) -> None:
    """Raise a ConfigError for the first merge key, `!!omap` or `!!pairs` in document order."""
    visited: set[int] = set()
    # Entries: (node, key path of the node, key path of the mapping holding the node when it is a key).
    stack: list[tuple[Node, tuple[str, ...], tuple[str, ...] | None]] = [(root, (), None)]
    while stack:
        node, key_path, holder = stack.pop()
        if holder is not None and node.tag == _MERGE_TAG:
            raise ConfigError(path, ".".join(holder) or None, _MERGE_REASON)
        if node.tag in _ORDERED_TAGS:
            raise ConfigError(path, ".".join(key_path) or None, _ORDERED_REASON)
        if id(node) in visited:
            continue
        visited.add(id(node))
        children: list[tuple[Node, tuple[str, ...], tuple[str, ...] | None]] = []
        if isinstance(node, MappingNode):
            for key_node, value_node in node.value:
                child_path = (*key_path, _parent_segment(key_node, top=not key_path))
                children.append((key_node, child_path, key_path))
                children.append((value_node, child_path, None))
        elif isinstance(node, SequenceNode):
            children.extend((item, (*key_path, f"[{i}]"), None) for i, item in enumerate(node.value))
        stack.extend(reversed(children))


def _compose(path: Path, yaml: YAML, data: bytes) -> Node | None:
    try:
        return yaml.compose(data)
    except Exception as exc:  # ruamel raises more than YAMLError
        raise ConfigError(path, None, _load_failure_reason(exc)) from exc


def _construct(path: Path, yaml: YAML, node: Node) -> object:
    try:
        return yaml.constructor.construct_document(node)
    except Exception as exc:  # ruamel raises more than YAMLError
        raise ConfigError(path, None, _load_failure_reason(exc)) from exc


def _parse(path: Path, data: bytes) -> Mapping[object, object] | None:
    """The file's top-level mapping, or None for a document with no content."""
    yaml = YAML(typ="safe", pure=True)  # Fresh per load: a reused instance keeps a `%YAML 1.1` directive's version.
    node = _compose(path, yaml, data)
    if yaml.version not in (None, (1, 2)):
        major, minor = yaml.version
        raise ConfigError(path, None, f"unsupported YAML version {major}.{minor}; use 1.2")
    if node is None:
        return None
    if node.tag in _ORDERED_TAGS:  # Before any construct: ruamel's own duplicate-key check is an `assert`.
        raise ConfigError(path, None, _ORDERED_REASON)
    if not isinstance(node, MappingNode):
        value = _construct(path, yaml, node)
        if value is None:
            return None
        raise ConfigError(path, None, f"expected a mapping at the top level, got {type(value).__name__}")
    # ruamel applies YAML 1.1's `<<` even in 1.2 mode, silently overriding or dropping entries. Its duplicate-key
    # check for `!!omap` and `!!pairs` is an `assert`, which `python -O` removes.
    _reject_unsupported(path, node)
    value = _construct(path, yaml, node)
    if not isinstance(value, Mapping):  # A `!!set` is a mapping node that constructs to a set.
        raise ConfigError(path, None, f"expected a mapping at the top level, got {type(value).__name__}")
    return value
