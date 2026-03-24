"""Domain models for Space and Patronus APIs."""

from .enums import (
    MRState,
    PushMode,
    ReviewRole,
    ReviewState,
    RunStatus,
    RunType,
    TimelineEventClass,
)
from .status import ACTIVE_STATUSES, FAILING, effective_status
from .patronus import (
    AttemptDetails,
    FailedBuild,
    FailedTest,
    PatronusCheckConfig,
    PatronusCheckRun,
    PatronusCheckRunAttempt,
    PatronusRun,
    Problem,
)
from .space import (
    Attachment,
    BranchPair,
    CodeDiscussion,
    Comment,
    FileAttachment,
    ImageAttachment,
    MergeRequest,
    Reviewer,
    SpaceAccount,
    SpaceApp,
    SpacePrincipal,
    TimelineItem,
    TimelineMessage,
    VideoAttachment,
    parse_attachments,
)

__all__ = [
    # Enums
    "MRState",
    "PushMode",
    "ReviewRole",
    "ReviewState",
    "RunStatus",
    "RunType",
    "TimelineEventClass",
    # Space models
    "SpacePrincipal",
    "SpaceAccount",
    "SpaceApp",
    "BranchPair",
    "Reviewer",
    "MergeRequest",
    "Attachment",
    "FileAttachment",
    "ImageAttachment",
    "VideoAttachment",
    "parse_attachments",
    "Comment",
    "CodeDiscussion",
    "TimelineMessage",
    "TimelineItem",
    # Status
    "ACTIVE_STATUSES",
    "FAILING",
    "effective_status",
    # Patronus models
    "PatronusRun",
    "PatronusCheckConfig",
    "PatronusCheckRun",
    "PatronusCheckRunAttempt",
    "AttemptDetails",
    "FailedTest",
    "FailedBuild",
    "Problem",
]
