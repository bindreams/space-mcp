import logging
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

    def test_mr_state_unknown(self):
        assert MRState("SomeNewState") == MRState.UNKNOWN

    def test_timeline_event_class_unknown(self):
        assert TimelineEventClass("NewEventType") == TimelineEventClass.UNKNOWN


class TestEnumsValues:
    """Enum values match API strings exactly."""

    def test_mr_state_values(self):
        assert MRState("Opened") == MRState.OPENED
        assert MRState("Closed") == MRState.CLOSED
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
