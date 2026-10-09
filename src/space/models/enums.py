"""Enum definitions for Space and Patronus API values.

Space enums are StrEnums whose values match the API strings exactly.
Patronus statuses are plain Enums, one per REST DTO level (run, check, attempt), so a status never equals
a string or a member of another level; display and JSON go through `.value`.
Each enum provides _missing_ to map unknown API values to UNKNOWN.
"""

from __future__ import annotations

import logging
from enum import Enum, StrEnum

_logger = logging.getLogger("space.models")

# Keys already logged by _PatronusStatus._missing_. Module-level: a set in an Enum class body would become a member.
_logged_unrecognised: set[tuple[str, str]] = set()


class _UnknownFallback(StrEnum):
    """Mixin: unknown values fall back to UNKNOWN."""

    @classmethod
    def _missing_(cls, value: object) -> StrEnum:
        # ty can't see that every subclass defines UNKNOWN; cls here is always a concrete subclass
        return cls.UNKNOWN  # type: ignore[return-value]  # ty: ignore[unresolved-attribute]


# Space enums ==========================================================================================================


class MRState(_UnknownFallback):
    """Actual review state returned by the API (CodeReviewState)."""

    OPENED = "Opened"
    CLOSED = "Closed"
    DELETED = "Deleted"
    UNKNOWN = "Unknown"


class MRStateFilter(_UnknownFallback):
    """Query filter for listing reviews (CodeReviewStateFilter)."""

    OPENED = "Opened"
    CLOSED = "Closed"
    MERGED = "Merged"
    REQUIRES_AUTHOR_ATTENTION = "RequiresAuthorAttention"
    NEEDS_REVIEW = "NeedsReview"
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


# Patronus enums =======================================================================================================


class _PatronusStatus(Enum):
    """Base of the per-DTO Patronus status enums."""

    @classmethod
    def _missing_(cls, value: object) -> _PatronusStatus:
        # repr keeps unhashable raw values usable as a key
        key = (cls.__name__, repr(value))
        if key not in _logged_unrecognised:
            _logged_unrecognised.add(key)
            # debug: no handler is configured, so a warning would print to stderr and garble `run watch`
            _logger.debug("unrecognised Patronus %s value %r", cls.__name__, value)
        # ty can't see the subclasses' UNKNOWN
        return cls.UNKNOWN  # type: ignore[attr-defined]  # ty: ignore[unresolved-attribute]


class RunStatus(_PatronusStatus):
    """RobotStatusDto."""

    RUNNING = "RUNNING"
    CANCELING = "CANCELING"
    CANCELED = "CANCELED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNKNOWN = "UNKNOWN"


class CheckStatus(_PatronusStatus):
    """TeamCityCheckStatusDto."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    FAILURE = "FAILURE"
    SUCCESS = "SUCCESS"
    CANCELED = "CANCELED"
    SKIPPED = "SKIPPED"
    UNKNOWN = "UNKNOWN"


class AttemptStatus(_PatronusStatus):
    """TeamCityCheckAttemptStatusDto."""

    RUNNING = "RUNNING"
    CANCELED = "CANCELED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
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
