"""A narrow https origin grammar for trust checks.

Deliberately strict: a loose grammar could merge two distinct hosts and trust the wrong one, while a strict one only
produces a loud "not trusted" error that the user can fix.
"""

import json
import re

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_AUTHORITY = rf"https://(?P<host>{_LABEL}(?:\.{_LABEL})*)(?::(?P<port>[0-9]{{1,5}}))?"

# re.ASCII keeps `[a-z]` under IGNORECASE from matching U+0130, U+0131, U+017F and the Kelvin sign.
_FLAGS = re.IGNORECASE | re.ASCII
_ORIGIN = re.compile(rf"{_AUTHORITY}/?", _FLAGS)
_URL_ORIGIN = re.compile(rf"{_AUTHORITY}(?=[/?#]|\Z)", _FLAGS)
_NUMERIC_LABEL = re.compile(r"[0-9]+|0x[0-9a-f]*", re.ASCII)
_AUTHORITY_END = re.compile(r"[/?#]")

_MAX_HOST_LENGTH = 253
_MAX_PORT = 65535
_DEFAULT_PORT = 443


def normalise_origin(url: str) -> str:
    """Return the canonical form of an origin-only https URL; raise ValueError if it is not one."""
    match = _ORIGIN.fullmatch(url)
    if match is None:
        raise ValueError(_describe(url, "is not a bare https origin (https://host[:port])"))
    return _canonical(url, match)


def origin_of(url: str) -> str:
    """Return the canonical origin of an https URL, ignoring whatever follows its authority."""
    match = _URL_ORIGIN.match(url)
    if match is None:
        raise ValueError(_describe(url, "does not start with an https origin (https://host[:port])"))
    return _canonical(url, match)


def _canonical(url: str, match: re.Match[str]) -> str:
    host = match["host"].lower()
    if len(host) > _MAX_HOST_LENGTH:
        raise ValueError(_describe(url, f"has a host longer than {_MAX_HOST_LENGTH} characters"))
    if _NUMERIC_LABEL.fullmatch(host.rsplit(".", 1)[-1]):
        raise ValueError(_describe(url, "has a numeric host (IP addresses are not accepted)"))
    port = match["port"]
    if port is None:
        return f"https://{host}"
    number = int(port)
    if not 1 <= number <= _MAX_PORT:
        raise ValueError(_describe(url, f"has a port outside 1-{_MAX_PORT}"))
    return f"https://{host}" if number == _DEFAULT_PORT else f"https://{host}:{number}"


def _describe(url: str, rule: str) -> str:
    message = f"{json.dumps(url, ensure_ascii=True)} {rule}"
    if url[:8].lower() == "https://":
        authority = url[8:]
        end = _AUTHORITY_END.search(authority)
        if not (authority[:end.start()] if end else authority).isascii():
            message += "; write internationalised hosts in punycode (xn--...) form"
    return message
