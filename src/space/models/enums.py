"""Enum definitions for Space and Patronus API values.

Space enums are StrEnums whose values match the API strings exactly.
Patronus statuses are plain Enums, one per REST DTO level (run, check, attempt), so a status never equals
a string or a member of another level; display and JSON go through `.value`.
Each enum provides _missing_: in strict mode an unknown API value raises UnrecognisedApiValue (except for the
exempt `_PermissiveFallback` enums); otherwise it maps to UNKNOWN, logged once at debug.
`_FallbackEnumType` takes the UNKNOWN placeholder's value out of the value lookup, so the placeholder is never accepted
from the wire: like any unmodelled value, it goes to `_missing_`.
"""

from __future__ import annotations

import logging
import threading
from enum import Enum, EnumType, StrEnum
from typing import Any, Self

_logger = logging.getLogger("space.models")

# Keys already logged by _log_unrecognised. Module-level: a set in an Enum class body would become a member.
_logged_unrecognised: set[tuple[str, str]] = set()

# Strict mode ==========================================================================================================


class UnrecognisedApiValue(ValueError):
    """Strict mode met an API enum value the client doesn't model, or a missing one."""

    def __init__(self, enum_name: str, value: object) -> None:
        # args are the constructor's own, so copy and pickle can rebuild the exception
        super().__init__(enum_name, value)
        self.enum_name = enum_name
        self.value = value

    def __str__(self) -> str:
        return f"{self.enum_name}: unrecognised value {self.value!r} (strict mode)"


_strict = False

# Where strict mode records each rejection as (enum name, repr(value)) before raising, when something installs a list.
# The test suite does, so a rejection the code under test catches still fails the test; production never reads it.
_strict_violations: list[tuple[str, str]] | None = None
# Guards _strict_violations: rejections can be recorded on any thread while the test hooks drain the list.
_violations_lock = threading.Lock()


def set_strict(enabled: bool) -> None:
    global _strict
    _strict = enabled


def is_strict() -> bool:
    return _strict


def _set_violation_record(record: list[tuple[str, str]] | None) -> list[tuple[str, str]] | None:
    """Install the list strict mode records rejections into (None: record nothing); return the previous one."""
    global _strict_violations
    with _violations_lock:
        previous, _strict_violations = _strict_violations, record
        return previous


def _violation_count() -> int:
    with _violations_lock:
        return 0 if _strict_violations is None else len(_strict_violations)


def _drain_violations(start: int = 0) -> list[tuple[str, str]]:
    """Remove and return the recorded rejections from index `start` on."""
    with _violations_lock:
        if _strict_violations is None:
            return []
        taken = _strict_violations[start:]
        del _strict_violations[start:]
        return taken


def _reject_if_strict(cls: type, value: object) -> None:
    """In strict mode, record the rejection (when a list is installed) and raise; otherwise do nothing."""
    if _strict:
        with _violations_lock:
            if _strict_violations is not None:
                _strict_violations.append((cls.__name__, repr(value)))
        raise UnrecognisedApiValue(cls.__name__, value)


# Fallback bases =======================================================================================================


def _log_unrecognised(message: str, cls: type, value: object) -> None:
    """Log an unrecognised API value once per (enum, value)."""
    # repr keeps unhashable raw values usable as a key
    key = (cls.__name__, repr(value))
    if key not in _logged_unrecognised:
        _logged_unrecognised.add(key)
        # debug: no handler is configured, so a warning would print to stderr and garble `run watch`
        _logger.debug(message, cls.__name__, value)


class _FallbackEnumType(EnumType):
    """Metaclass of the fallback bases: every enum with members defines UNKNOWN, which no value lookup can reach."""

    def __new__(mcls, name: str, bases: tuple[type, ...], classdict: Any, **kwargs: Any) -> Any:
        cls = super().__new__(mcls, name, bases, classdict, **kwargs)
        if cls._member_map_:
            assert "UNKNOWN" in cls._member_map_, f"{name} has members but no UNKNOWN"
            # every lookup of the placeholder's value, by any call shape, now misses and goes to `_missing_`
            del cls._value2member_map_[cls._member_map_["UNKNOWN"]._value_]
        return cls


def _reduce_by_name(member: Enum) -> tuple[Any, ...]:
    # Pickle by name: unpickling `cls("Unknown")` would go through `_missing_`
    return getattr, (type(member), member._name_)


class _UnknownFallback(StrEnum, metaclass=_FallbackEnumType):
    """Mixin: unknown values raise in strict mode and fall back to UNKNOWN otherwise."""

    @classmethod
    def _missing_(cls, value: object) -> Self:
        _reject_if_strict(cls, value)
        _log_unrecognised("unrecognised %s value %r", cls, value)
        # ty can't see that every subclass defines UNKNOWN; the metaclass asserts it
        return cls.UNKNOWN  # ty: ignore[unresolved-attribute]

    def __reduce_ex__(self, proto: object) -> tuple[Any, ...]:
        return _reduce_by_name(self)


class _PermissiveFallback(StrEnum, metaclass=_FallbackEnumType):
    """Mixin for enums exempt from strict mode: unknown values always fall back to UNKNOWN."""

    @classmethod
    def _missing_(cls, value: object) -> Self:
        _log_unrecognised("unrecognised %s value %r", cls, value)
        # ty can't see that every subclass defines UNKNOWN; the metaclass asserts it
        return cls.UNKNOWN  # ty: ignore[unresolved-attribute]

    def __reduce_ex__(self, proto: object) -> tuple[Any, ...]:
        return _reduce_by_name(self)


# Space enums ==========================================================================================================


class MRState(_UnknownFallback):
    """Actual review state returned by the API (CodeReviewState)."""

    OPENED = "Opened"
    CLOSED = "Closed"
    DELETED = "Deleted"
    UNKNOWN = "Unknown"


class MRStateFilter(_PermissiveFallback):
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


class TimelineEventClass(_PermissiveFallback):
    MC_MESSAGE = "MCMessage"
    M2_TEXT_ITEM = "M2TextItemContent"
    CODE_DISCUSSION_ADDED = "CodeDiscussionAddedFeedEvent"
    UNKNOWN = "Unknown"


# Patronus enums =======================================================================================================


class _PatronusStatus(Enum, metaclass=_FallbackEnumType):
    """Base of the per-DTO Patronus status enums; unknown values raise in strict mode, as for `_UnknownFallback`."""

    @classmethod
    def _missing_(cls, value: object) -> Self:
        _reject_if_strict(cls, value)
        _log_unrecognised("unrecognised Patronus %s value %r", cls, value)
        # ty can't see the subclasses' UNKNOWN; the metaclass asserts it
        return cls.UNKNOWN  # ty: ignore[unresolved-attribute]

    def __reduce_ex__(self, proto: object) -> tuple[Any, ...]:
        return _reduce_by_name(self)


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
    """PushModeDto."""

    DRY_RUN = "DRY_RUN"
    MERGE = "MERGE"
    REBASE = "REBASE"
    REBASE_AUTOSQUASH = "REBASE_AUTOSQUASH"
    SQUASH_ALL = "SQUASH_ALL"
    UNKNOWN = "UNKNOWN"


class RunType(_UnknownFallback):
    """RobotTypeDto."""

    WEB_UI = "WEB_UI"
    SAFE_PUSH = "SAFE_PUSH"
    SPACE_REVIEW_CHERRY_PICK = "SPACE_REVIEW_CHERRY_PICK"
    PATRONUS_CHERRY_PICK = "PATRONUS_CHERRY_PICK"
    SPACE_SAFE_MERGE = "SPACE_SAFE_MERGE"
    CUSTOM = "CUSTOM"
    GITHUB_PR = "GITHUB_PR"
    UNKNOWN = "UNKNOWN"
