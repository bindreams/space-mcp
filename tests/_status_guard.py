"""Records every unrecognised Patronus status value, with the phase that parsed it.

The `_PatronusStatus._missing_` wrapper is installed when this module is imported, so parses made while the test
modules, conftests and factories are imported are recorded too; `tests/conftest.py` imports it before any `space.*`
module. Records made before `pytest_configure` claims the state are buffered with phase "collection".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from space.models import enums

Record = tuple[str, str, str]  # (enum class name, repr(value), phase)


@dataclass
class GuardState:
    phase: str = "collection"
    records: list[Record] = field(default_factory=list)
    item_start: int = 0  # index into records where the current item's records begin
    item_violations: dict[str, str] = field(default_factory=dict)  # item nodeid -> message
    session_messages: list[str] = field(default_factory=list)  # item violations, reported again at session finish


_BASE = enums._PatronusStatus
_ORIGINAL = _BASE.__dict__["_missing_"]
_pending = GuardState()  # buffers records until a config claims it
_stack: list[GuardState] = []  # claimed states; the last one is active (nested in-process runs push)
_installed = False


def _active() -> GuardState:
    return _stack[-1] if _stack else _pending


def _missing_(cls, value):
    state = _active()
    state.records.append((cls.__name__, repr(value), state.phase))
    return _ORIGINAL.__func__(cls, value)


def install() -> None:
    global _installed
    if not _installed:
        _BASE._missing_ = classmethod(_missing_)  # ty: ignore[invalid-assignment]  # replaced and restored by the guard
        _installed = True


def uninstall() -> None:
    global _installed
    if _installed:
        _BASE._missing_ = _ORIGINAL  # ty: ignore[invalid-assignment]  # restores the original
        _installed = False


def claim() -> GuardState:
    """Make a state active for one pytest config: the import-time buffer first, a fresh one for nested runs."""
    global _pending
    install()
    if _stack:
        state = GuardState()
    else:
        state, _pending = _pending, GuardState()
    _stack.append(state)
    return state


def release(state: GuardState) -> None:
    _stack.remove(state)
    if not _stack:
        uninstall()


install()
