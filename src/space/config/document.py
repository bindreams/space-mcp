"""Parsing the YAML document and rejecting constructs the config file does not support."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

from ruamel.yaml import YAML
from ruamel.yaml.reader import ReaderError
from ruamel.yaml.tokens import DirectiveToken, StreamStartToken
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from space.config.errors import ConfigError
from space.config.keys import _key_segment, _top_segment

_STR_TAG = "tag:yaml.org,2002:str"
_MERGE_TAG = "tag:yaml.org,2002:merge"
_SET_TAG = "tag:yaml.org,2002:set"
_VALUE_TAG = "tag:yaml.org,2002:value"
_MAPPING_TAGS = ("tag:yaml.org,2002:map", _SET_TAG)
_ORDERED_TAGS = ("tag:yaml.org,2002:omap", "tag:yaml.org,2002:pairs")
_MERGE_REASON = "merge keys (<<) are not supported"
_ORDERED_REASON = "ordered-map tags (!!omap, !!pairs) are not supported"


def _load_failure_reason(exc: Exception) -> str:
    # Never str(exc): ruamel quotes source lines, which may carry unsafe printable characters.
    reason = f"invalid YAML ({type(exc).__name__})"
    if isinstance(exc, ReaderError):  # Its `reason` is ruamel's own text and `position` a byte offset.
        return f"{reason}: {json.dumps(str(exc.reason), ensure_ascii=True)} at byte {exc.position}"
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


class _Entry(NamedTuple):
    node: Node
    key_path: tuple[str, ...]  # the node's own key path
    holder: tuple[str, ...] | None  # key path of the mapping holding the node, when the node is a key
    seen: set[tuple[str, str]] | None  # the (tag, value) of the keys already met in that mapping


def _dotted(key_path: tuple[str, ...]) -> str | None:
    return ".".join(key_path) or None


def _reject_key(path: Path, entry: _Entry, visited: set[int]) -> None:
    node, holder, seen = entry.node, entry.holder, entry.seen
    assert holder is not None and seen is not None
    if node.tag == _MERGE_TAG:
        raise ConfigError(path, _dotted(holder), _MERGE_REASON)
    if node.tag == _VALUE_TAG:
        raise ConfigError(path, _dotted(holder), "value keys (=) are not supported")
    if id(node) in visited:
        raise ConfigError(path, _dotted(holder), "keys must not be aliases")
    if not isinstance(node, ScalarNode):
        raise ConfigError(path, _dotted(holder), "keys must be plain scalars")
    identity = (node.tag, node.value)
    if identity in seen:
        mark = node.start_mark
        key = _parent_segment(node, top=False)
        raise ConfigError(
            path, _dotted(holder), f"duplicate key {key} at line {mark.line + 1}, column {mark.column + 1}"
        )
    seen.add(identity)


def _reject_unsupported(path: Path, root: Node) -> None:
    """Raise a ConfigError for the first construct the config file does not support, in document order.

    Keys are compared as nodes: ruamel's own duplicate check formats the values, which grow exponentially through
    aliases, and compares Python values, so `1` and `true` would collide.
    """
    visited: set[int] = set()
    stack = [_Entry(root, (), None, None)]
    while stack:
        entry = stack.pop()
        node, key_path = entry.node, entry.key_path
        if entry.holder is not None:
            _reject_key(path, entry, visited)
        if node.tag in _ORDERED_TAGS:
            raise ConfigError(path, _dotted(key_path), _ORDERED_REASON)
        if id(node) in visited:
            continue
        visited.add(id(node))
        children: list[_Entry] = []
        if isinstance(node, MappingNode):
            if node.tag not in _MAPPING_TAGS:
                raise ConfigError(
                    path, _dotted(key_path),
                    f"tag {json.dumps(node.tag, ensure_ascii=True)} is not supported on a mapping"
                )
            seen: set[tuple[str, str]] = set()
            for key_node, value_node in node.value:
                child_path = (*key_path, _parent_segment(key_node, top=not key_path))
                children.append(_Entry(key_node, child_path, key_path, seen))
                children.append(_Entry(value_node, child_path, None, None))
        elif isinstance(node, SequenceNode):
            children.extend(_Entry(item, (*key_path, f"[{i}]"), None, None) for i, item in enumerate(node.value))
        stack.extend(reversed(children))


def _declared_version(path: Path, yaml: YAML, data: bytes) -> tuple[int, int] | None:
    """The `%YAML` directive's version. Scanned, not composed: ruamel's parser asserts on versions other than 1.1 and 1.2."""
    try:
        for token in yaml.scan(data):
            if isinstance(token, DirectiveToken):
                if token.name == "YAML":
                    return token.value
            elif not isinstance(token, StreamStartToken):
                return None
    except Exception as exc:  # ruamel raises more than YAMLError
        raise ConfigError(path, None, _load_failure_reason(exc)) from exc
    return None


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
    # Reusing an anchor is legal; ruamel's warning would echo raw source lines (bidi overrides included) to stderr.
    yaml.composer.warn_double_anchors = False
    yaml.allow_duplicate_keys = True  # `_reject_unsupported` reports duplicates; ruamel's own message formats values.
    version = _declared_version(path, yaml, data)
    if version is not None and version != (1, 2):
        raise ConfigError(path, None, f"unsupported YAML version {version[0]}.{version[1]}; use 1.2")
    node = _compose(path, yaml, data)
    if node is None:
        return None
    if node.tag in _ORDERED_TAGS:  # Before any construct: ruamel's own duplicate-key check is an `assert`.
        raise ConfigError(path, None, _ORDERED_REASON)
    # The shape comes first, from the node alone: constructing a wrong-shaped document could fail on unrelated content.
    if isinstance(node, SequenceNode):
        raise ConfigError(path, None, "expected a mapping at the top level, got list")
    if isinstance(node, MappingNode) and node.tag == _SET_TAG:
        raise ConfigError(path, None, "expected a mapping at the top level, got set")
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
