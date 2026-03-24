"""Derived display status for Patronus runs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from .enums import RunStatus

if TYPE_CHECKING:
    from .patronus import PatronusCheckRun, PatronusRun

FAILING = "FAILING"
ACTIVE_STATUSES = frozenset({RunStatus.RUNNING, RunStatus.PENDING, RunStatus.STARTING})


def effective_status(run: PatronusRun, checks: Sequence[PatronusCheckRun] | None = None) -> str:
    """Derive display status for a Patronus run.

    Returns "FAILING" if the run is active but has definitively failed checks
    (Patronus exhausted all retries). Returns "UNKNOWN" if any check has an
    unrecognized status. Otherwise returns the raw run status string.

    Priority: FAILURE > UNKNOWN > raw status.

    Returns str (not RunStatus) because FAILING is a display concept, not an API value.
    """
    if run.status not in ACTIVE_STATUSES:
        return run.status.value

    if not checks:
        return run.status.value

    has_unknown = False
    for check in checks:
        if check.status == RunStatus.FAILURE:
            return FAILING
        if check.status == RunStatus.UNKNOWN:
            has_unknown = True

    if has_unknown:
        return RunStatus.UNKNOWN.value

    return run.status.value
