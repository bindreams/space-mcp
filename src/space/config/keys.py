"""Setting names and the formatting of key paths."""

import json

_STRICT_KEY = "strict"
_ENDPOINTS_KEY = "patronus-trusted-endpoints"
_KNOWN_KEYS = (_STRICT_KEY, _ENDPOINTS_KEY)


def _key_segment(key: object) -> str:
    return json.dumps(key, ensure_ascii=True) if isinstance(key, str) else f"<{type(key).__name__} key>"


def _top_segment(key: object) -> str:
    """First segment of a key path: the known setting names appear bare."""
    return key if isinstance(key, str) and key in _KNOWN_KEYS else _key_segment(key)
