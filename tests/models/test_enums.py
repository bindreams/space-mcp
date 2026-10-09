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
    @pytest.mark.unrecognised_patronus_status
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
