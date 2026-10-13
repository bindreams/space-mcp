"""Parsing the YAML document and rejecting constructs the config file does not support."""

import json
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from space.config.errors import ConfigError
from space.config.keys import _key_segment, _top_segment

_STR_TAG = "tag:yaml.org,2002:str"
_MERGE_TAG = "tag:yaml.org,2002:merge"


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
