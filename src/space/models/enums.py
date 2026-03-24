"""StrEnum definitions for Space and Patronus API values.

Values match API strings exactly — StrEnum compares by value.
Each enum provides _missing_ to map unknown API values to UNKNOWN.
"""

from enum import StrEnum


class _UnknownFallback(StrEnum):
    """Mixin: unknown values fall back to UNKNOWN."""

    @classmethod
    def _missing_(cls, value: object) -> StrEnum:
        return cls.UNKNOWN  # type: ignore[return-value]


# Space enums =====


class MRState(_UnknownFallback):
    OPENED = "Opened"
    CLOSED = "Closed"
    MERGED = "Merged"
    UNKNOWN = "Unknown"


class ReviewRole(_UnknownFallback):
    AUTHOR = "Author"
    REVIEWER = "Reviewer"
    WATCHER = "Watcher"
    UNKNOWN = "Unknown"


class ReviewState(_UnknownFallback):
    ACCEPTED = "Accepted"
    REJECTED = "Rejected"
    RESUMED = "Resumed"
    PENDING = "Pending"
    UNKNOWN = "Unknown"


class TimelineEventClass(_UnknownFallback):
    MC_MESSAGE = "MCMessage"
    M2_TEXT_ITEM = "M2TextItemContent"
    CODE_DISCUSSION_ADDED = "CodeDiscussionAddedFeedEvent"
    UNKNOWN = "Unknown"


# Patronus enums =====


class RunStatus(_UnknownFallback):
    RUNNING = "RUNNING"
    PENDING = "PENDING"
    STARTING = "STARTING"
    SUCCESS = "SUCCESS"
    SUCCESSFUL = "SUCCESSFUL"
    FAILURE = "FAILURE"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class PushMode(_UnknownFallback):
    DRY_RUN = "DRY_RUN"
    MERGE = "MERGE"
    REBASE = "REBASE"
    REBASE_AUTOSQUASH = "REBASE_AUTOSQUASH"
    REBASE_SQUASH_ALL = "REBASE_SQUASH_ALL"
    UNKNOWN = "UNKNOWN"


class RunType(_UnknownFallback):
    SAFE_PUSH = "SAFE_PUSH"
    UNKNOWN = "UNKNOWN"
