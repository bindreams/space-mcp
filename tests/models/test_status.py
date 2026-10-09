"""Tests for effective_status derivation logic and fetch_checks_for_running."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import space.patronus
from space.models import PatronusCheckRun, PatronusRun
from space.models import enums
from space.models.status import ACTIVE_STATUSES, FAILING, effective_status

from tests.sample_responses import wire_check, wire_run


# Helpers ==============================================================================================================
async def _run(status: str, **overrides) -> PatronusRun:
    # Owner resolves from the cache that the test_accounts fixture fills, so the client is unused.
    return await PatronusRun.from_api(wire_run(status, **overrides), None)


def _checks(*statuses: str) -> list[PatronusCheckRun]:
    return [PatronusCheckRun.from_api(wire_check(s, name=f"Check {i}")) for i, s in enumerate(statuses)]


# ACTIVE_STATUSES ======================================================================================================


def test_active_statuses_are_running_and_canceling():
    assert ACTIVE_STATUSES == frozenset({enums.RunStatus.RUNNING, enums.RunStatus.CANCELING})


# Runs that are not RUNNING ============================================================================================


@pytest.mark.usefixtures("test_accounts")
class TestNotRunningIgnoresChecks:
    """Every status except RUNNING, CANCELING included, is returned as-is, ignoring checks."""

    @pytest.mark.parametrize("status", ["FAILURE", "SUCCESS", "CANCELED", "CANCELING"])
    async def test_without_checks(self, status):
        assert effective_status(await _run(status)) == status

    @pytest.mark.parametrize("status", ["FAILURE", "SUCCESS", "CANCELED", "CANCELING"])
    async def test_ignores_failed_checks(self, status):
        assert effective_status(await _run(status), _checks("FAILURE")) == status

    @pytest.mark.unrecognised_patronus_status
    async def test_unknown_run_ignores_failed_checks(self):
        assert effective_status(await _run("NO_SUCH"), _checks("FAILURE")) == "UNKNOWN"

    async def test_canceling_with_failed_check_is_canceling(self):
        # regression guard: passes before and after CANCELING joins ACTIVE_STATUSES
        assert effective_status(await _run("CANCELING"), _checks("FAILURE")) == "CANCELING"

    @pytest.mark.unrecognised_patronus_status
    async def test_canceling_with_unknown_check_is_canceling(self):
        # regression guard: passes before and after CANCELING joins ACTIVE_STATUSES
        assert effective_status(await _run("CANCELING"), _checks("SUCCESS", "NO_SUCH")) == "CANCELING"


# RUNNING runs =========================================================================================================


@pytest.mark.usefixtures("test_accounts")
class TestRunningWithChecks:
    """A RUNNING run shows FAILING over UNKNOWN over RUNNING, by its checks."""

    async def test_no_checks(self):
        assert effective_status(await _run("RUNNING")) == "RUNNING"

    async def test_checks_none(self):
        assert effective_status(await _run("RUNNING"), None) == "RUNNING"

    async def test_checks_empty(self):
        assert effective_status(await _run("RUNNING"), []) == "RUNNING"

    async def test_all_success(self):
        assert effective_status(await _run("RUNNING"), _checks("SUCCESS", "SUCCESS")) == "RUNNING"

    async def test_with_queued_check_is_running(self):
        assert effective_status(await _run("RUNNING"), _checks("QUEUED", "SUCCESS")) == "RUNNING"

    async def test_with_canceled_check_is_running(self):
        assert effective_status(await _run("RUNNING"), _checks("CANCELED", "RUNNING")) == "RUNNING"

    async def test_mix_success_and_running(self):
        assert effective_status(await _run("RUNNING"), _checks("SUCCESS", "RUNNING")) == "RUNNING"

    async def test_one_failure_is_failing(self):
        assert effective_status(await _run("RUNNING"), _checks("SUCCESS", "FAILURE")) == FAILING

    @pytest.mark.unrecognised_patronus_status
    async def test_unknown_check_is_unknown(self):
        assert effective_status(await _run("RUNNING"), _checks("SUCCESS", "NO_SUCH")) == "UNKNOWN"

    async def test_with_failure_and_queued_checks_is_failing(self):
        # regression guard: the lower-precedence check comes first
        assert effective_status(await _run("RUNNING"), _checks("QUEUED", "FAILURE")) == FAILING

    @pytest.mark.unrecognised_patronus_status
    async def test_with_failure_and_unknown_checks_is_failing(self):
        # regression guard: the lower-precedence check comes first
        assert effective_status(await _run("RUNNING"), _checks("NO_SUCH", "FAILURE")) == FAILING

    async def test_with_canceled_and_skipped_checks_is_running(self):
        assert effective_status(await _run("RUNNING"), _checks("CANCELED", "SKIPPED")) == "RUNNING"


# fetch_checks_for_running =============================================================================================


@pytest.mark.usefixtures("test_accounts")
class TestFetchChecksForRunning:
    """Tests for the shared check-fetching helper."""

    async def test_only_fetches_running_runs(self):
        running = await _run("RUNNING", id="run-running")
        finished = await _run("SUCCESS", id="run-finished")
        mock_patronus = MagicMock()
        mock_patronus.get_run_teamcity_checks = AsyncMock(return_value=_checks("SUCCESS"))

        result = await space.patronus.fetch_checks_for_running(mock_patronus, [running, finished])

        assert list(result) == ["run-running"]
        mock_patronus.get_run_teamcity_checks.assert_called_once_with("run-running")

    async def test_skips_canceling(self):
        canceling = await _run("CANCELING", id="run-canceling")
        running = await _run("RUNNING", id="run-running")
        mock_patronus = MagicMock()
        mock_patronus.get_run_teamcity_checks = AsyncMock(return_value=_checks("SUCCESS"))

        result = await space.patronus.fetch_checks_for_running(mock_patronus, [canceling, running])

        assert list(result) == ["run-running"]
        mock_patronus.get_run_teamcity_checks.assert_called_once_with("run-running")

    async def test_empty_when_no_running_runs(self):
        finished = await _run("SUCCESS")
        mock_patronus = MagicMock()
        mock_patronus.get_run_teamcity_checks = AsyncMock()

        assert await space.patronus.fetch_checks_for_running(mock_patronus, [finished]) == {}
        mock_patronus.get_run_teamcity_checks.assert_not_called()

    async def test_dropped_fetch_is_logged(self, caplog):
        running = await _run("RUNNING", id="run-dropped")
        mock_patronus = MagicMock()
        mock_patronus.get_run_teamcity_checks = AsyncMock(side_effect=RuntimeError("boom"))

        result = await space.patronus.fetch_checks_for_running(mock_patronus, [running])

        assert result == {}
        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert any("run-dropped" in m and "boom" in m for m in warnings)

    async def test_skips_runs_whose_fetch_was_cancelled(self, caplog):
        # gather(return_exceptions=True) returns a child's CancelledError as a value; it is not an Exception.
        running = await _run("RUNNING", id="run-cancelled")
        mock_patronus = MagicMock()
        mock_patronus.get_run_teamcity_checks = AsyncMock(side_effect=asyncio.CancelledError())

        result = await space.patronus.fetch_checks_for_running(mock_patronus, [running])

        assert result == {}
        assert any("run-cancelled" in r.getMessage() for r in caplog.records if r.levelname == "WARNING")
