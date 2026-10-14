from __future__ import annotations

import dataclasses
import sys

import pytest

from space.models.review_ref import ReviewRef
from tests.factories import make_mr


def test_number_ref():
    ref = ReviewRef(number=42)
    assert ref.path_segment == "number:42"
    assert str(ref) == "#42"


def test_id_ref():
    ref = ReviewRef(id="abc")
    assert ref.path_segment == "id:abc"
    assert str(ref) == "id:abc"


@pytest.mark.parametrize("kwargs", [{}, {"number": 1, "id": "x"}])
def test_needs_exactly_one(kwargs):
    with pytest.raises(ValueError, match="exactly one of number and id"):
        ReviewRef(**kwargs)


@pytest.mark.parametrize(("number", "error"), [(0, ValueError), (-1, ValueError), (True, TypeError), (1.0, TypeError),
                                               ("42", TypeError)])
def test_number_must_be_positive_int(number, error):
    with pytest.raises(error):
        ReviewRef(number=number)


@pytest.mark.parametrize(("value", "error"), [("", ValueError), (42, TypeError)])
def test_id_must_be_non_empty_str(value, error):
    with pytest.raises(error):
        ReviewRef(id=value)


def test_frozen():
    ref = ReviewRef(number=42)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.number = 43


def test_equality_and_hash():
    assert ReviewRef(number=42) == ReviewRef(number=42)
    assert hash(ReviewRef(number=42)) == hash(ReviewRef(number=42))
    assert ReviewRef(number=42) != ReviewRef(id="42")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("42", ReviewRef(number=42)),
        ("042", ReviewRef(number=42)),
        ("99999999999999999999", ReviewRef(number=99999999999999999999)),
        ("number:42", ReviewRef(number=42)),
        ("2eTFJg4dJrmL", ReviewRef(id="2eTFJg4dJrmL")),
        ("²", ReviewRef(id="²")),
        ("١٢", ReviewRef(id="١٢")),
        ("٣", ReviewRef(id="٣")),
        (" 42", ReviewRef(id=" 42")),
        ("42\n", ReviewRef(id="42\n")),
        ("4²", ReviewRef(id="4²")),
        ("id:123456", ReviewRef(id="123456")),
        ("id:number:1", ReviewRef(id="number:1")),
        ("ID:x", ReviewRef(id="ID:x")),
        ("Number:1", ReviewRef(id="Number:1")),
    ],
)
def test_parse(text, expected):
    assert ReviewRef.parse(text) == expected


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "empty merge request reference"),
        ("0", "merge request numbers start at 1, got '0'"),
        ("000", "merge request numbers start at 1, got '000'"),
        ("number:0", "merge request numbers start at 1, got 'number:0'"),
        ("id:", "empty merge request id in 'id:'"),
        ("number:", "not a merge request number: 'number:'"),
        ("number:x", "not a merge request number: 'number:x'"),
        ("number:²", "not a merge request number: 'number:²'"),
    ],
)
def test_parse_rejects(text, message):
    with pytest.raises(ValueError) as excinfo:
        ReviewRef.parse(text)
    assert str(excinfo.value) == message


@pytest.fixture()
def digit_limit():
    """The interpreter's int-conversion digit limit; an unlimited interpreter gets the default for the test."""
    original = sys.get_int_max_str_digits()
    if original == 0:
        sys.set_int_max_str_digits(4300)
    yield sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(original)


def test_parse_rejects_a_number_beyond_the_digit_limit(digit_limit):
    digits = "9" * (digit_limit + 1)
    with pytest.raises(ValueError) as excinfo:
        ReviewRef.parse(digits)
    assert str(excinfo.value) == f"merge request number too large: {digits[:20]}…"


def test_for_mr_numbered():
    assert ReviewRef.for_mr(make_mr(number=188120, id="123456")) == ReviewRef(number=188120)


def test_for_mr_number_less():
    assert ReviewRef.for_mr(make_mr(number=0, id="123456")) == ReviewRef(id="123456")


@pytest.mark.parametrize(("number", "error"), [(-5, ValueError), (True, TypeError), (1.5, TypeError)])
def test_for_mr_rejects_invalid_number(number, error):
    with pytest.raises(error, match="'123456'"):
        ReviewRef.for_mr(make_mr(number=number, id="123456"))


def test_parse_versus_for_mr():
    assert ReviewRef.parse("123456") == ReviewRef(number=123456)
    ref = ReviewRef.for_mr(make_mr(number=0, id="123456"))
    assert ref == ReviewRef(id="123456")
    assert ReviewRef.parse(str(ref)) == ref


@pytest.mark.parametrize(
    ("ref", "segment"),
    [
        (ReviewRef(number=42), "number:42"),
        (ReviewRef(id="2eTFJg4dJrmL"), "id:2eTFJg4dJrmL"),
        (ReviewRef(id="x/../number:5"), "id:x%2F..%2Fnumber%3A5"),
        (ReviewRef(id="abc#"), "id:abc%23"),
        (ReviewRef(id="a?b"), "id:a%3Fb"),
        (ReviewRef(id="²"), "id:%C2%B2"),
    ],
)
def test_url_segment_encodes_the_id(ref, segment):
    assert ref.url_segment == segment


def test_path_segment_keeps_the_raw_id():
    assert ReviewRef(id="x/../number:5").path_segment == "id:x/../number:5"


@pytest.mark.parametrize(("ref", "label"), [(ReviewRef(number=42), "42"), (ReviewRef(id="123456"), "id:123456")])
def test_label_is_the_bare_number_or_the_explicit_id(ref, label):
    assert ref.label == label
    assert ReviewRef.parse(ref.label) == ref
