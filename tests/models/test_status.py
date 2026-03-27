"""Tests for effective_status derivation logic and fetch_checks_for_active."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from space.models import (
    PatronusCheckConfig,
    PatronusCheckRun,
    PatronusRun,
    RunStatus,
    SpaceAccount,
)
from space.models.status import FAILING, effective_status
from space.patronus import fetch_checks_for_active

# Helpers ==============================================================================================================

_ACCOUNT = SpaceAccount(
    id="user-test",
    username="tester",
    email="t@test.com",
    first_name="Test",
    last_name="User",
)

_NOW = datetime(2026, 3, 24, 12, 0, 0, tzinfo=timezone.utc)

_CHECK_CONFIG = PatronusCheckConfig(
    name="Compile All",
    build_configuration_id="compile_id",
    build_configuration_name="Compile All Build",
    build_configuration_url=None,
    project_name="Project",
    attempt_limit=3,
)

_run_counter = 0


def _make_run(status: RunStatus) -> PatronusRun:
    from space.models.enums import PushMode, RunType
    from space.models.space import BranchPair

    global _run_counter
    _run_counter += 1
    return PatronusRun(
        id=f"run-{_run_counter}",
        name="Test run",
        status=status,
        push_mode=PushMode.DRY_RUN,
        branch_pair=BranchPair(source_branch="feature", target_branch="main", repository="repo"),
        owner=_ACCOUNT,
        started_at=_NOW,
        run_type=RunType.SAFE_PUSH,
    )


def _make_check(status: RunStatus) -> PatronusCheckRun:
    return PatronusCheckRun(
        id="check-1",
        config=_CHECK_CONFIG,
        status=status,
        queued_at=_NOW,
        started_at=_NOW,
        finished_at=None,
        skip_reason=None,
        attempts=(),
    )


# Terminal statuses ====================================================================================================


class TestTerminalStatuses:
    """Terminal run statuses are returned as-is, ignoring checks."""

    @pytest.mark.parametrize(
        "status", [
            RunStatus.FAILURE,
            RunStatus.SUCCESS,
            RunStatus.SUCCESSFUL,
            RunStatus.CANCELLED,
            RunStatus.UNKNOWN,
        ]
    )
    def test_terminal_without_checks(self, status):
        run = _make_run(status)
        assert effective_status(run) == status.value

    @pytest.mark.parametrize(
        "status", [
            RunStatus.FAILURE,
            RunStatus.SUCCESS,
            RunStatus.SUCCESSFUL,
            RunStatus.CANCELLED,
            RunStatus.UNKNOWN,
        ]
    )
    def test_terminal_ignores_failed_checks(self, status):
        run = _make_run(status)
        checks = [_make_check(RunStatus.FAILURE)]
        assert effective_status(run, checks) == status.value


# Active statuses without failures =====================================================================================


class TestActiveNoFailures:
    """Active runs without failed checks return raw status."""

    def test_running_no_checks(self):
        assert effective_status(_make_run(RunStatus.RUNNING)) == "RUNNING"

    def test_running_checks_none(self):
        assert effective_status(_make_run(RunStatus.RUNNING), None) == "RUNNING"

    def test_running_checks_empty(self):
        assert effective_status(_make_run(RunStatus.RUNNING), []) == "RUNNING"

    def test_running_all_success(self):
        checks = [_make_check(RunStatus.SUCCESS), _make_check(RunStatus.SUCCESS)]
        assert effective_status(_make_run(RunStatus.RUNNING), checks) == "RUNNING"

    def test_running_mix_success_and_running(self):
        checks = [_make_check(RunStatus.SUCCESS), _make_check(RunStatus.RUNNING)]
        assert effective_status(_make_run(RunStatus.RUNNING), checks) == "RUNNING"


# Active statuses with failures ========================================================================================


class TestActiveFailing:
    """Active runs with failed checks return FAILING."""

    def test_running_one_failure(self):
        checks = [_make_check(RunStatus.SUCCESS), _make_check(RunStatus.FAILURE)]
        assert effective_status(_make_run(RunStatus.RUNNING), checks) == FAILING

    def test_pending_one_failure(self):
        checks = [_make_check(RunStatus.FAILURE)]
        assert effective_status(_make_run(RunStatus.PENDING), checks) == FAILING

    def test_starting_one_failure(self):
        checks = [_make_check(RunStatus.FAILURE)]
        assert effective_status(_make_run(RunStatus.STARTING), checks) == FAILING


# UNKNOWN checks =======================================================================================================


class TestUnknownChecks:
    """UNKNOWN check status surfaces as UNKNOWN; FAILURE takes priority."""

    def test_running_unknown_check(self):
        checks = [_make_check(RunStatus.SUCCESS), _make_check(RunStatus.UNKNOWN)]
        assert effective_status(_make_run(RunStatus.RUNNING), checks) == "UNKNOWN"

    def test_failure_takes_priority_over_unknown(self):
        checks = [_make_check(RunStatus.FAILURE), _make_check(RunStatus.UNKNOWN)]
        assert effective_status(_make_run(RunStatus.RUNNING), checks) == FAILING


# fetch_checks_for_active ==============================================================================================


class TestFetchChecksForActive:
    """Tests for the shared check-fetching helper."""

    async def test_only_fetches_active_runs(self):
        running = _make_run(RunStatus.RUNNING)
        finished = _make_run(RunStatus.SUCCESS)
        mock_patronus = MagicMock()
        mock_patronus.get_run_teamcity_checks = AsyncMock(return_value=[_make_check(RunStatus.SUCCESS)])

        result = await fetch_checks_for_active(mock_patronus, [running, finished])
        assert running.id in result
        assert finished.id not in result
        mock_patronus.get_run_teamcity_checks.assert_called_once_with(running.id)

    async def test_empty_when_no_active_runs(self):
        finished = _make_run(RunStatus.SUCCESS)
        mock_patronus = MagicMock()
        mock_patronus.get_run_teamcity_checks = AsyncMock()

        result = await fetch_checks_for_active(mock_patronus, [finished])
        assert result == {}
        mock_patronus.get_run_teamcity_checks.assert_not_called()

    async def test_swallows_exceptions(self):
        running = _make_run(RunStatus.RUNNING)
        mock_patronus = MagicMock()
        mock_patronus.get_run_teamcity_checks = AsyncMock(side_effect=Exception("API error"))

        result = await fetch_checks_for_active(mock_patronus, [running])
        assert result == {}
