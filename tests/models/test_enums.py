"""Tests for StrEnum definitions."""

from space.models.enums import (
    MRState,
    PushMode,
    ReviewRole,
    ReviewState,
    RunStatus,
    RunType,
    TimelineEventClass,
)


class TestEnumsMissing:
    """Unknown API values map to UNKNOWN, not raise."""

    def test_mr_state_unknown(self):
        assert MRState("SomeNewState") == MRState.UNKNOWN

    def test_run_status_unknown(self):
        assert RunStatus("SOME_NEW") == RunStatus.UNKNOWN

    def test_timeline_event_class_unknown(self):
        assert TimelineEventClass("NewEventType") == TimelineEventClass.UNKNOWN


class TestEnumsValues:
    """Enum values match API strings exactly."""

    def test_mr_state_values(self):
        assert MRState("Opened") == MRState.OPENED
        assert MRState("Closed") == MRState.CLOSED
        assert MRState("Merged") == MRState.MERGED

    def test_review_role_values(self):
        assert ReviewRole("Author") == ReviewRole.AUTHOR
        assert ReviewRole("Reviewer") == ReviewRole.REVIEWER
        assert ReviewRole("Watcher") == ReviewRole.WATCHER

    def test_review_state_values(self):
        assert ReviewState("Accepted") == ReviewState.ACCEPTED
        assert ReviewState("Rejected") == ReviewState.REJECTED
        assert ReviewState("Resumed") == ReviewState.RESUMED
        assert ReviewState("Pending") == ReviewState.PENDING

    def test_run_status_both_success_variants(self):
        assert RunStatus("SUCCESS") == RunStatus.SUCCESS
        assert RunStatus("SUCCESSFUL") == RunStatus.SUCCESSFUL
        assert RunStatus.SUCCESS != RunStatus.SUCCESSFUL

    def test_run_status_values(self):
        assert RunStatus("RUNNING") == RunStatus.RUNNING
        assert RunStatus("FAILURE") == RunStatus.FAILURE
        assert RunStatus("CANCELLED") == RunStatus.CANCELLED
        assert RunStatus("SKIPPED") == RunStatus.SKIPPED

    def test_skipped_is_not_unknown(self):
        assert RunStatus("SKIPPED") != RunStatus.UNKNOWN

    def test_push_mode_values(self):
        assert PushMode("DRY_RUN") == PushMode.DRY_RUN
        assert PushMode("MERGE") == PushMode.MERGE

    def test_run_type_values(self):
        assert RunType("SAFE_PUSH") == RunType.SAFE_PUSH

    def test_timeline_event_class_values(self):
        assert TimelineEventClass("MCMessage") == TimelineEventClass.MC_MESSAGE
        assert TimelineEventClass("M2TextItemContent") == TimelineEventClass.M2_TEXT_ITEM
        assert TimelineEventClass("CodeDiscussionAddedFeedEvent") == TimelineEventClass.CODE_DISCUSSION_ADDED
