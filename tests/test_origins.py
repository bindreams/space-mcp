"""Tests for the https origin grammar."""

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from space.origins import _LABEL as LABEL
from space.origins import normalise_origin, origin_of

KELVIN = "K"

# Hosts that are not valid in either function.
BAD_HOSTS = [
    "",
    "a..b",
    ".a",
    "a.",
    "-a.com",
    "a-.com",
    "a" * 64 + ".com",
    ".".join(["a" * 63] * 4),  # 255 characters
    "1.2.3.4",
    "127.1",
    "0x7f.1",
    "1.0x7f",
    "0X7F000001",
    "1.0x",
    "0x",
    "2130706433",
    "[::1]",
    "exa_mple.com",
]
BAD_PORTS = ["+443", "1_0", "٤٤٣", "", "0", "99999", "65536", "-1", "4 43"]
NON_ASCII_HOSTS = ["é.com", "İ.com", "ı.com", "ſ.com", f"{KELVIN}ey.com"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://example.com", "https://example.com"),
        ("https://Example.COM", "https://example.com"),
        ("https://example.com/", "https://example.com"),
        ("https://example.com:443", "https://example.com"),
        ("https://example.com:443/", "https://example.com"),
        ("https://example.com:0443", "https://example.com"),
        ("https://example.com:8443", "https://example.com:8443"),
        ("https://example.com:1", "https://example.com:1"),
        ("https://example.com:65535", "https://example.com:65535"),
        ("HTTPS://example.com", "https://example.com"),
        ("https://" + "a" * 63 + ".com", "https://" + "a" * 63 + ".com"),
        ("https://xn--nxasmq6b.com", "https://xn--nxasmq6b.com"),
        ("https://localhost", "https://localhost"),
        ("https://1a.com", "https://1a.com"),
        ("https://a.0xg", "https://a.0xg"),
    ],
)
def test_normalise_origin_accepts(raw, expected):
    assert normalise_origin(raw) == expected


def test_normalise_origin_accepts_253_character_host():
    host = ".".join(["a" * 63] * 3 + ["a" * 61])
    assert len(host) == 253
    assert normalise_origin(f"https://{host}") == f"https://{host}"


@pytest.mark.parametrize(
    "raw",
    [
        "https://example.com/path",
        "https://example.com/a/../b",
        "https://example.com/.",
        "https://example.com/..",
        "https://example.com?",
        "https://example.com?q=1",
        "https://example.com#",
        "https://example.com#frag",
        "https://example.com@evil.com",
        "https://user@example.com",
        "https://user:pw@example.com",
        "http://example.com",
        "example.com",
        "https://",
        "https:///",
        "https://:443",
        "ftp://example.com",
        "https://example.com\n",
        "https://example.com ",
        " https://example.com",
        "https://exa mple.com",
        "https://example.com\t",
        "https://example.com:443\n",
        "https://" + "a" * 64 + ".com",
        "https://" + ".".join(["a" * 63] * 3 + ["a" * 62]),
        *(f"https://{h}" for h in BAD_HOSTS),
        *(f"https://{h}" for h in NON_ASCII_HOSTS),
        *(f"https://example.com:{p}" for p in BAD_PORTS),
        "https://example.com:123456",
    ],
)
def test_normalise_origin_rejects(raw):
    with pytest.raises(ValueError):
        normalise_origin(raw)


@pytest.mark.parametrize("host", NON_ASCII_HOSTS)
def test_normalise_origin_non_ascii_host_hints_punycode(host):
    with pytest.raises(ValueError, match="punycode"):
        normalise_origin(f"https://{host}")


def test_non_ascii_hint_only_for_host_part():
    with pytest.raises(ValueError) as exc:
        normalise_origin("https://example.com/é")
    assert "punycode" not in str(exc.value)


def test_rejected_input_is_json_escaped():
    with pytest.raises(ValueError) as exc:
        normalise_origin("https://exa\x1bmple.com")
    assert "\\u001b" in str(exc.value)
    assert "\x1b" not in str(exc.value)


def test_rejected_non_ascii_input_is_json_escaped():
    with pytest.raises(ValueError) as exc:
        normalise_origin("https://é.com")
    assert "\\u00e9" in str(exc.value)
    assert "é" not in str(exc.value)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://example.com", "https://example.com"),
        ("https://Example.com/path?q=1#frag", "https://example.com"),
        ("https://example.com:443/path", "https://example.com"),
        ("https://example.com:8443/path", "https://example.com:8443"),
        ("https://example.com?q=1", "https://example.com"),
        ("https://example.com#frag", "https://example.com"),
        ("https://example.com/", "https://example.com"),
        ("https://example.com/a b\n", "https://example.com"),
        ("https://example.com/a@b", "https://example.com"),
        ("https://example.com/é中", "https://example.com"),
        ("https://example.com?é", "https://example.com"),
        ("https://example.com#é x", "https://example.com"),
    ],
)
def test_origin_of_accepts(raw, expected):
    assert origin_of(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        f"https://{KELVIN}ey.com/path",
        "https://example.com@evil.com/path",
        "https://user@example.com/path",
        "https://example.com\n/path",
        "https://example.com /path",
        "https://example.com\n",
        "https://example.com:443x/path",
        "http://example.com/path",
        "example.com/path",
        "https:///path",
        "",
        *(f"https://{h}/path" for h in BAD_HOSTS),
        *(f"https://{h}/path" for h in NON_ASCII_HOSTS),
        *(f"https://example.com:{p}/path" for p in BAD_PORTS),
        "https://example.com:123456/path",
    ],
)
def test_origin_of_rejects(raw):
    with pytest.raises(ValueError):
        origin_of(raw)


@pytest.mark.parametrize("host", NON_ASCII_HOSTS)
def test_origin_of_non_ascii_host_hints_punycode(host):
    with pytest.raises(ValueError, match="punycode"):
        origin_of(f"https://{host}/path")


def test_origin_of_rejected_input_is_json_escaped():
    with pytest.raises(ValueError) as exc:
        origin_of("https://exa\x1bmple.com/x")
    assert "\\u001b" in str(exc.value)


# Properties ===========================================================================================================

_NUMERIC_LAST = r"[0-9]+|0x[0-9a-f]*"


@st.composite
def _labels(draw):
    label = draw(st.from_regex(LABEL, fullmatch=True))
    return "".join(draw(st.sampled_from([c.lower(), c.upper()])) for c in label)


@st.composite
def valid_origins(draw, *, suffix=False):
    labels = draw(st.lists(_labels(), min_size=1, max_size=6))
    labels[-1] = draw(_labels().filter(lambda x: not re.fullmatch(_NUMERIC_LAST, x.lower(), re.ASCII)))
    host = ".".join(labels)
    if len(host) > 253:
        host = labels[-1]
    out = "https://" + host
    if draw(st.booleans()):
        port = draw(st.integers(1, 65535))
        zeros = draw(st.integers(0, 5 - len(str(port))))
        out += ":" + "0" * zeros + str(port)
    if suffix:
        if draw(st.booleans()):
            out += draw(st.sampled_from("/?#")) + draw(st.text())
    elif draw(st.booleans()):
        out += "/"
    return out


@given(st.text())
def test_normalise_origin_only_raises_value_error(text):
    try:
        normalise_origin(text)
    except ValueError:
        pass


@given(st.text())
def test_origin_of_only_raises_value_error(text):
    try:
        origin_of(text)
    except ValueError:
        pass


@given(valid_origins())
def test_normalise_origin_succeeds_and_is_idempotent(raw):
    once = normalise_origin(raw)
    assert normalise_origin(once) == once


@given(valid_origins())
def test_origin_of_matches_normalise_origin_for_origin_only(raw):
    assert origin_of(raw) == normalise_origin(raw)


@given(valid_origins(suffix=True))
def test_origin_of_result_is_canonical(raw):
    result = origin_of(raw)
    assert normalise_origin(result) == result


@pytest.mark.parametrize("scheme", ["HTTPS://", "Https://", "hTtPs://"])
@pytest.mark.parametrize("fn", [normalise_origin, origin_of])
def test_punycode_hint_for_any_scheme_case(fn, scheme):
    with pytest.raises(ValueError, match="punycode"):
        fn(f"{scheme}\u00e9.com/x" if fn is origin_of else f"{scheme}\u00e9.com")


def test_origin_of_host_length_boundary():
    host253 = ".".join(["a" * 63] * 3 + ["a" * 61])
    assert origin_of(f"https://{host253}/x") == f"https://{host253}"
    with pytest.raises(ValueError):
        origin_of(f"https://{host253}a/x")
    with pytest.raises(ValueError):
        origin_of("https://" + ".".join(["a" * 63] * 3 + ["a" * 62]) + "/x")


def test_origin_of_non_ascii_after_authority_gives_no_hint():
    with pytest.raises(ValueError) as exc:
        origin_of("https://exa mple.com/\u00e9")
    assert "punycode" not in str(exc.value)


@st.composite
def _scheme_prefixed(draw):
    scheme = "".join(draw(st.sampled_from([c.lower(), c.upper()])) for c in "https")
    return draw(st.sampled_from(["https://", scheme + "://"])) + draw(st.text())


@given(st.text().map(lambda s: "https://" + s))
def test_functions_raise_only_value_error_after_scheme(text):
    for fn in (normalise_origin, origin_of):
        try:
            fn(text)
        except ValueError:
            pass


@given(_scheme_prefixed())
def test_functions_raise_only_value_error_after_random_case_scheme(text):
    for fn in (normalise_origin, origin_of):
        try:
            fn(text)
        except ValueError:
            pass
