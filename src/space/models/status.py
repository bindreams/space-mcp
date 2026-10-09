"""Derived display status for Patronus runs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from .enums import CheckStatus, RunStatus

if TYPE_CHECKING:
    from .patronus import PatronusCheckRun, PatronusRun

FAILING = "FAILING"
ACTIVE_STATUSES = frozenset({RunStatus.RUNNING, RunStatus.CANCELING})


def effective_status(run: PatronusRun, checks: Sequence[PatronusCheckRun] | None = None) -> str:
    """Derive display status for a Patronus run.

    Only a RUNNING run's checks affect its status, in order of precedence:
    "FAILING" if any check is FAILURE (Patronus exhausted all retries), "UNKNOWN" if any
    check is UNKNOWN, otherwise "RUNNING". Every other status, CANCELING included, is
    returned as-is.

    Returns str (not RunStatus) because FAILING is a display concept, not an API value.
    """
    if run.status is not RunStatus.RUNNING or not checks:
        return run.status.value

    has_unknown = False
    for check in checks:
        if check.status is CheckStatus.FAILURE:
            return FAILING
        if check.status is CheckStatus.UNKNOWN:
            has_unknown = True

    if has_unknown:
        return RunStatus.UNKNOWN.value

    return run.status.value
