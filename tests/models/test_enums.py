import copy
import json
import logging
import pickle
import subprocess
import sys
from enum import Enum

import pytest

from space.models import enums
from space.models.enums import (
    MRState,
    MRStateFilter,
    PushMode,
    ReviewRole,
    ReviewState,
    RunType,
    TimelineEventClass,
)


class TestEnumsMissing:
    """Unknown API values map to UNKNOWN, not raise."""

    @pytest.mark.unrecognised_api_value
    def test_mr_state_unknown(self):
        assert MRState("SomeNewState") == MRState.UNKNOWN

    def test_timeline_event_class_unknown(self):
        assert TimelineEventClass("NewEventType") == TimelineEventClass.UNKNOWN


class TestEnumsValues:
    """Enum values match API strings exactly."""

    def test_mr_state_values(self):
        assert MRState("Opened") == MRState.OPENED
        assert MRState("Closed") == MRState.CLOSED

    @pytest.mark.unrecognised_api_value
    def test_mr_state_has_no_merged_member(self):
        # MRState has no MERGED — merged MRs have actual state Closed
        assert MRState("Merged") == MRState.UNKNOWN

    def test_mr_state_filter_values(self):
        assert MRStateFilter("Opened") == MRStateFilter.OPENED
        assert MRStateFilter("Closed") == MRStateFilter.CLOSED
        assert MRStateFilter("Merged") == MRStateFilter.MERGED
        assert MRStateFilter("RequiresAuthorAttention") == MRStateFilter.REQUIRES_AUTHOR_ATTENTION
        assert MRStateFilter("NeedsReview") == MRStateFilter.NEEDS_REVIEW

    def test_review_role_values(self):
        assert ReviewRole("Author") == ReviewRole.AUTHOR
        assert ReviewRole("Reviewer") == ReviewRole.REVIEWER
        assert ReviewRole("Watcher") == ReviewRole.WATCHER

    def test_review_state_values(self):
        assert ReviewState("Accepted") == ReviewState.ACCEPTED
        assert ReviewState("Rejected") == ReviewState.REJECTED
        assert ReviewState("Resumed") == ReviewState.RESUMED
        assert ReviewState("Pending") == ReviewState.PENDING

    def test_push_mode_values(self):
        assert PushMode("DRY_RUN") == PushMode.DRY_RUN
        assert PushMode("MERGE") == PushMode.MERGE

    def test_run_type_values(self):
        assert RunType("SAFE_PUSH") == RunType.SAFE_PUSH

    def test_timeline_event_class_values(self):
        assert TimelineEventClass("MCMessage") == TimelineEventClass.MC_MESSAGE
        assert TimelineEventClass("M2TextItemContent") == TimelineEventClass.M2_TEXT_ITEM
        assert TimelineEventClass("CodeDiscussionAddedFeedEvent") == TimelineEventClass.CODE_DISCUSSION_ADDED


class TestPatronusStatusValues:
    """Each level's members are exactly the values its Patronus DTO enum sends, plus UNKNOWN."""

    @pytest.mark.parametrize("name", ["RunStatus", "CheckStatus", "AttemptStatus"])
    @pytest.mark.parametrize("never_sent", ["PENDING", "STARTING", "SUCCESSFUL", "CANCELLED"])
    @pytest.mark.unrecognised_api_value
    def test_values_patronus_never_sends_are_unknown(self, name, never_sent):
        enum = getattr(enums, name)
        assert enum(never_sent) is enum.UNKNOWN

    @pytest.mark.parametrize("name", ["RunStatus", "CheckStatus", "AttemptStatus"])
    def test_levels_share_a_base_but_are_not_str(self, name):
        enum = getattr(enums, name)
        assert issubclass(enum, enums._PatronusStatus)
        assert not issubclass(enum, str)

    def test_levels_and_strings_are_unequal(self):
        assert enums.RunStatus.SUCCESS != "SUCCESS"
        assert enums.RunStatus.SUCCESS != enums.CheckStatus.SUCCESS
        assert enums.CheckStatus.SUCCESS != enums.AttemptStatus.SUCCESS
        assert enums.RunStatus.RUNNING.value == enums.CheckStatus.RUNNING.value == "RUNNING"


# Fallback bases =======================================================================================================

_BASES = (enums._UnknownFallback, enums._PatronusStatus, enums._PermissiveFallback)


def _enums_by_base() -> dict[type, set[type]]:
    """Every member-bearing enum in `space.models.enums`, grouped by the fallback bases it derives from."""
    grouped: dict[type, set[type]] = {base: set() for base in _BASES}
    for obj in vars(enums).values():
        if isinstance(obj, type) and issubclass(obj, Enum) and obj not in _BASES and len(obj.__members__):
            for base in _BASES:
                if issubclass(obj, base):
                    grouped[base].add(obj)
    return grouped


class TestFallbackBases:

    def test_every_enum_has_exactly_one_fallback_base(self):
        grouped = _enums_by_base()
        assert grouped[enums._PermissiveFallback] == {TimelineEventClass, MRStateFilter}
        every = [e for group in grouped.values() for e in group]
        assert len(every) == len(set(every)), "an enum derives from more than one fallback base"
        defined = {
            obj
            for obj in vars(enums).values() if isinstance(obj, type) and issubclass(obj, Enum)
            and obj.__module__ == enums.__name__ and obj not in _BASES
        }
        assert set(every) == defined

    def test_permissive_unrecognised_is_unknown_and_logged_once(self, caplog):
        caplog.set_level(logging.DEBUG, logger="space.models")
        for enum, raw in ((TimelineEventClass, "NewFeedEvent"), (MRStateFilter, "opened")):
            assert enum(raw) is enum.UNKNOWN
            assert enum(raw) is enum.UNKNOWN
        records = [(r.name, r.levelno, r.getMessage()) for r in caplog.records]
        assert records == [
            ("space.models", logging.DEBUG, "unrecognised TimelineEventClass value 'NewFeedEvent'"),
            ("space.models", logging.DEBUG, "unrecognised MRStateFilter value 'opened'"),
        ]

    def test_mr_state_filter_accepts_its_five_members(self, caplog):
        caplog.set_level(logging.DEBUG, logger="space.models")
        expected = {
            "Opened": MRStateFilter.OPENED,
            "Closed": MRStateFilter.CLOSED,
            "Merged": MRStateFilter.MERGED,
            "RequiresAuthorAttention": MRStateFilter.REQUIRES_AUTHOR_ATTENTION,
            "NeedsReview": MRStateFilter.NEEDS_REVIEW,
        }
        assert {raw: MRStateFilter(raw) for raw in expected} == expected
        assert caplog.records == []


# Placeholder routing ==================================================================================================

# One literal message prefix per base; `_log_unrecognised` appends the value's repr.
_PREFIX = {
    enums._UnknownFallback: "unrecognised {name} value",
    enums._PatronusStatus: "unrecognised Patronus {name} value",
    enums._PermissiveFallback: "unrecognised {name} value",
}

_ALL_ENUMS = sorted((e for group in _enums_by_base().values() for e in group), key=lambda e: e.__name__)


def _message(enum: type, value: object) -> str:
    base = next(b for b in _BASES if issubclass(enum, b))
    return f"{_PREFIX[base].format(name=enum.__name__)} {value!r}"


def _messages(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "space.models"]


_BY_NAME = pytest.mark.parametrize("enum", _ALL_ENUMS, ids=lambda e: e.__name__)

# Every way to look a value up. 3.12+ treats a second argument, even `names=None`, as part of a tuple value.
_TUPLE_LOOKUP = sys.version_info >= (3, 12)
_CALL_SHAPES = {
    "positional": (lambda e, v: e(v), False),
    "keyword": (lambda e, v: e(value=v), False),
    "module": (lambda e, v: e(v, module="m"), False),
    "names-none": (lambda e, v: e(v, names=None), _TUPLE_LOOKUP),
    "positional-none": (lambda e, v: e(v, None), _TUPLE_LOOKUP),
    "enum-new": (lambda e, v: Enum.__new__(e, v), False),
}
_BY_SHAPE = pytest.mark.parametrize("shape", list(_CALL_SHAPES))


class TestPlaceholderUnreachable:

    @pytest.mark.unrecognised_api_value
    @_BY_SHAPE
    @_BY_NAME
    def test_placeholder_literal_is_unknown_and_logged(self, caplog, enum, shape):
        caplog.set_level(logging.DEBUG, logger="space.models")
        call, as_tuple = _CALL_SHAPES[shape]
        literal = enum.UNKNOWN.value
        assert call(enum, literal) is enum.UNKNOWN
        assert _messages(caplog) == [_message(enum, (literal, None) if as_tuple else literal)]

    @pytest.mark.unrecognised_api_value
    def test_foreign_placeholder_member_is_unrecognised(self, caplog):
        caplog.set_level(logging.DEBUG, logger="space.models")
        assert ReviewState(MRState.UNKNOWN) is ReviewState.UNKNOWN
        assert _messages(caplog) == [f"unrecognised ReviewState value {MRState.UNKNOWN!r}"]

    @pytest.mark.unrecognised_api_value
    @pytest.mark.parametrize("raw", [None, 1, ["x"]], ids=["none", "int", "unhashable"])
    @_BY_NAME
    def test_non_string_values_are_unknown_and_logged(self, caplog, enum, raw):
        caplog.set_level(logging.DEBUG, logger="space.models")
        assert enum(raw) is enum.UNKNOWN
        assert enum(raw) is enum.UNKNOWN
        assert _messages(caplog) == [_message(enum, raw)]

    @pytest.mark.parametrize("mode", ["strict", pytest.param("permissive", marks=pytest.mark.unrecognised_api_value)])
    @_BY_NAME
    def test_members_pass_through(self, caplog, enum, mode):
        caplog.set_level(logging.DEBUG, logger="space.models")
        for member in enum:
            assert enum(member) is member
            assert enum(value=member) is member
        assert _messages(caplog) == []

    def test_every_enum_defines_unknown(self):
        assert all("UNKNOWN" in e.__members__ for e in _ALL_ENUMS)
        with pytest.raises(AssertionError, match="NoPlaceholder"):

            class NoPlaceholder(enums._UnknownFallback):
                A = "a"

        with pytest.raises(AssertionError, match="Dyn"):
            enums._UnknownFallback("Dyn", [("A", "a")])

    @pytest.mark.parametrize("keyword", [False, True], ids=["positional", "keyword"])
    @pytest.mark.parametrize("base", _BASES, ids=lambda b: b.__name__)
    def test_calling_a_base_is_enum_type_error(self, base, keyword):
        with pytest.raises(TypeError, match="no members"):
            base(value="x") if keyword else base("x")

    @pytest.mark.unrecognised_api_value
    def test_functional_api_placeholder_is_unrecognised(self, caplog):
        caplog.set_level(logging.DEBUG, logger="space.models")
        dyn = enums._UnknownFallback("Dyn", [("A", "a"), ("UNKNOWN", "Unknown")])
        assert dyn("a") is dyn.A
        assert dyn("Unknown") is dyn.UNKNOWN
        assert _messages(caplog) == ["unrecognised Dyn value 'Unknown'"]

    @pytest.mark.unrecognised_api_value
    def test_multi_argument_call_follows_enum_type(self, caplog):
        caplog.set_level(logging.DEBUG, logger="space.models")
        if sys.version_info < (3, 12):
            with pytest.raises(TypeError):
                MRState("Unknown", "extra")
            assert _messages(caplog) == []
        else:  # 3.12+ looks the argument tuple up as one value
            assert MRState("Unknown", "extra") is MRState.UNKNOWN
            assert _messages(caplog) == ["unrecognised MRState value ('Unknown', 'extra')"]

    @_BY_NAME
    def test_members_pickle_and_copy_by_identity(self, caplog, enum):
        caplog.set_level(logging.DEBUG, logger="space.models")
        for member in enum:
            for protocol in (0, pickle.HIGHEST_PROTOCOL):
                assert pickle.loads(pickle.dumps(member, protocol)) is member
            assert copy.copy(member) is member
            assert copy.deepcopy(member) is member
        assert _messages(caplog) == []


# Strict mode ==========================================================================================================

_STRICT_ENUMS = sorted(
    _enums_by_base()[enums._UnknownFallback] | _enums_by_base()[enums._PatronusStatus], key=lambda e: e.__name__
)

_STRICT_BY_NAME = pytest.mark.parametrize("enum", _STRICT_ENUMS, ids=lambda e: e.__name__)


class TestStrictMode:

    @pytest.mark.raises_unrecognised_api_value
    @pytest.mark.parametrize("raw", ["NEW_VALUE", None, 1, ["x"]], ids=["unmodelled", "none", "int", "unhashable"])
    @_STRICT_BY_NAME
    def test_strict_unrecognised_value_raises(self, enum, raw):
        with pytest.raises(enums.UnrecognisedApiValue):
            enum(raw)

    @pytest.mark.raises_unrecognised_api_value
    @_BY_SHAPE
    @_STRICT_BY_NAME
    def test_strict_placeholder_literal_raises(self, enum, shape):
        call, as_tuple = _CALL_SHAPES[shape]
        literal = enum.UNKNOWN.value
        with pytest.raises(enums.UnrecognisedApiValue) as info:
            call(enum, literal)
        assert info.value.value == ((literal, None) if as_tuple else literal)
        assert enums._drain_violations() == [(enum.__name__, repr(info.value.value))]

    def test_members_and_iteration_keep_the_placeholder(self):
        assert MRState.UNKNOWN in MRState
        assert list(MRState) == [MRState.OPENED, MRState.CLOSED, MRState.DELETED, MRState.UNKNOWN]
        assert list(MRState.__members__) == ["OPENED", "CLOSED", "DELETED", "UNKNOWN"]

    def test_strict_placeholder_membership(self):
        """`in` on a raw value differs by version: 3.11 rejects it, 3.12 looks it up, 3.13 compares member values."""
        if sys.version_info < (3, 12):
            with pytest.warns(DeprecationWarning), pytest.raises(TypeError):
                "Unknown" in MRState  # noqa: B015 -- the lookup is the test
        elif sys.version_info < (3, 13):
            assert "Unknown" not in MRState  # the lookup raised UnrecognisedApiValue, which `in` treats as absent
            assert enums._drain_violations() == [("MRState", "'Unknown'")]
        else:
            assert "Unknown" in MRState
            assert enums._drain_violations() == []

    @pytest.mark.raises_unrecognised_api_value
    def test_strict_foreign_placeholder_member_raises(self):
        with pytest.raises(enums.UnrecognisedApiValue):
            ReviewState(MRState.UNKNOWN)

    @pytest.mark.raises_unrecognised_api_value
    def test_strict_error_carries_name_and_value(self):
        with pytest.raises(enums.UnrecognisedApiValue) as info:
            enums.RunStatus("NEW")
        assert info.value.enum_name == "RunStatus"
        assert info.value.value == "NEW"
        assert str(info.value) == "RunStatus: unrecognised value 'NEW' (strict mode)"
        assert isinstance(info.value, ValueError)

    @pytest.mark.parametrize(
        "clone",
        [copy.copy, copy.deepcopy, lambda e: pickle.loads(pickle.dumps(e))],
        ids=["copy", "deepcopy", "pickle"],
    )
    def test_error_copies_and_pickles(self, clone):
        original = enums.UnrecognisedApiValue("RunStatus", ["not", "hashable"])
        cloned = clone(original)
        assert type(cloned) is enums.UnrecognisedApiValue
        assert (cloned.enum_name, cloned.value) == ("RunStatus", ["not", "hashable"])
        assert str(cloned) == str(original) == "RunStatus: unrecognised value ['not', 'hashable'] (strict mode)"

    @pytest.mark.raises_unrecognised_api_value
    def test_strict_raise_records_and_does_not_log(self, caplog):
        caplog.set_level(logging.DEBUG, logger="space.models")
        with pytest.raises(enums.UnrecognisedApiValue):
            enums.RunStatus("NEW")
        assert enums._drain_violations() == [("RunStatus", "'NEW'")]
        assert _messages(caplog) == []

    def test_exempt_enums_stay_permissive_in_strict_mode(self, caplog):
        caplog.set_level(logging.DEBUG, logger="space.models")
        assert TimelineEventClass("NewFeedEvent") is TimelineEventClass.UNKNOWN
        assert TimelineEventClass("Unknown") is TimelineEventClass.UNKNOWN
        assert MRStateFilter("opened") is MRStateFilter.UNKNOWN
        assert _messages(caplog) == [
            "unrecognised TimelineEventClass value 'NewFeedEvent'",
            "unrecognised TimelineEventClass value 'Unknown'",
            "unrecognised MRStateFilter value 'opened'",
        ]

    def test_strict_pickle_round_trips_unknown(self):
        for member in (enums.RunStatus.UNKNOWN, MRState.UNKNOWN):
            assert pickle.loads(pickle.dumps(member)) is member


_DEFAULT_PROBE = """
import json
from space.models import enums
print(json.dumps([enums.is_strict(), enums.RunStatus("NEW_STATUS") is enums.RunStatus.UNKNOWN]))
"""


def test_strict_mode_is_off_in_a_fresh_interpreter():
    """Shipped behaviour: until something turns strict on, an unmodelled value is UNKNOWN, not an error."""
    result = subprocess.run([sys.executable, "-c", _DEFAULT_PROBE], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [False, True]


class _LoggingLock:
    """Stands in for `enums._violations_lock`, logging when it is held."""

    def __init__(self, log: list[str]):
        self.log = log

    def __enter__(self):
        self.log.append("acquire")

    def __exit__(self, *exc):
        self.log.append("release")


class _LoggingRecord(list):
    """A violation record that logs each mutation or read the drain and the rejection make."""

    def __init__(self, log: list[str]):
        super().__init__()
        self.log = log

    def append(self, item):
        self.log.append("append")
        super().append(item)

    def __getitem__(self, index):
        self.log.append("read")
        return super().__getitem__(index)

    def __delitem__(self, index):
        self.log.append("delete")
        super().__delitem__(index)


class TestViolationRecord:

    def test_record_and_drain_run_under_the_lock(self, monkeypatch):
        log: list[str] = []
        record = _LoggingRecord(log)
        previous = enums._set_violation_record(record)
        try:
            monkeypatch.setattr(enums, "_violations_lock", _LoggingLock(log))
            with pytest.raises(enums.UnrecognisedApiValue):
                enums.RunStatus("NEW")
            assert log == ["acquire", "append", "release"]
            log.clear()
            assert enums._drain_violations() == [("RunStatus", "'NEW'")]
            assert log == ["acquire", "read", "delete", "release"]
        finally:
            monkeypatch.undo()
            enums._set_violation_record(previous)
