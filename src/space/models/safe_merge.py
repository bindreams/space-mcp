"""The body Space returns for a safe-merge or dry-run request."""

from __future__ import annotations

from dataclasses import dataclass

_NEEDS_MESSAGE = ("Error", "Progress")


def _unexpected(reason: str) -> ValueError:
    return ValueError(f"unexpected safe-merge response: {reason}")


@dataclass(frozen=True)
class SafeMergeEvent:
    type: str | None
    message: str | None


@dataclass(frozen=True)
class SafeMergeStart:
    """A started safe merge: run fields from a dict body, or `events` (a tuple, maybe empty) from a list body."""

    run_id: str | None = None
    run_url: str | None = None
    status: str | None = None
    job_id: str | None = None
    events: tuple[SafeMergeEvent, ...] | None = None

    @classmethod
    def from_api(cls, data: object) -> SafeMergeStart:
        """Parse the body; `None` is an empty body.

        Raises:
            ValueError: a shape or value type this client doesn't understand.
        """
        if data is None:
            return cls()
        if isinstance(data, dict):
            return cls(
                run_id=_field(data, "robotId"),
                run_url=_field(data, "robotUrl"),
                status=_field(data, "status"),
                job_id=_field(data, "jobId"),
            )
        if isinstance(data, list):
            return cls(events=tuple(_event(item) for item in data))
        raise _unexpected(f"a {type(data).__name__} body")


def _field(data: dict, key: str) -> str | None:
    if key not in data:
        return None
    value = data[key]
    if not isinstance(value, str) or not value:
        raise _unexpected(f"{key} is {value!r}")
    return value


def _event(item: object) -> SafeMergeEvent:
    if not isinstance(item, dict):
        raise _unexpected(f"an event is a {type(item).__name__}")
    kind = item.get("type")
    message = item.get("message")
    if kind is not None and not isinstance(kind, str):
        raise _unexpected(f"an event type is {kind!r}")
    if message is not None and not isinstance(message, str):
        raise _unexpected(f"an event message is {message!r}")
    if kind in _NEEDS_MESSAGE and message is None:
        raise _unexpected(f"a {kind} event has no message")
    return SafeMergeEvent(kind, message)
