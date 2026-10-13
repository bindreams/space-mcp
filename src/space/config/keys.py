"""Setting names and the formatting of key paths."""

import json

STRICT_KEY = "strict"
ENDPOINTS_KEY = "patronus-trusted-endpoints"
# File key -> Config field. The one place a setting is declared.
SETTINGS = {STRICT_KEY: "strict", ENDPOINTS_KEY: "trusted_endpoint_overrides"}
KNOWN_KEYS = tuple(SETTINGS)


def key_segment(key: object) -> str:
    return json.dumps(key, ensure_ascii=True) if isinstance(key, str) else f"<{type(key).__name__} key>"


def top_segment(key: object) -> str:
    """First segment of a key path: the known setting names appear bare."""
    return key if isinstance(key, str) and key in KNOWN_KEYS else key_segment(key)
