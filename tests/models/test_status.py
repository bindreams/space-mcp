"""Tests for effective_status derivation logic and fetch_checks_for_running."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

import space.patronus
from space.models import PatronusCheckRun, PatronusRun
from space.models.status import FAILING, effective_status

from tests.sample_responses import wire_check, wire_run


# Helpers ==============================================================================================================
async def _run(status: str, **overrides) -> PatronusRun:
    # Owner resolves from the cache that the test_accounts fixture fills, so the client is unused.
    return await PatronusRun.from_api(wire_run(status, **overrides), None)


def _checks(*statuses: str) -> list[PatronusCheckRun]:
    return [PatronusCheckRun.from_api(wire_check(s, name=f"Check {i}")) for i, s in enumerate(statuses)]


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

    @pytest.mark.unrecognised_api_value
    async def test_unknown_run_ignores_failed_checks(self):
        assert effective_status(await _run("NO_SUCH"), _checks("FAILURE")) == "UNKNOWN"

    async def test_canceling_with_failed_check_is_canceling(self):
        assert effective_status(await _run("CANCELING"), _checks("FAILURE")) == "CANCELING"

    @pytest.mark.unrecognised_api_value
    async def test_canceling_with_unknown_check_is_canceling(self):
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

    @pytest.mark.unrecognised_api_value
    async def test_unknown_check_is_unknown(self):
        assert effective_status(await _run("RUNNING"), _checks("SUCCESS", "NO_SUCH")) == "UNKNOWN"

    async def test_with_failure_and_queued_checks_is_failing(self):
        assert effective_status(await _run("RUNNING"), _checks("QUEUED", "FAILURE")) == FAILING

    @pytest.mark.unrecognised_api_value
    async def test_with_failure_and_unknown_checks_is_failing(self):
        # lower-precedence check first
        assert effective_status(await _run("RUNNING"), _checks("NO_SUCH", "FAILURE")) == FAILING

    async def test_with_canceled_and_skipped_checks_is_running(self):
        assert effective_status(await _run("RUNNING"), _checks("CANCELED", "SKIPPED")) == "RUNNING"


# fetch_checks_for_running =============================================================================================


@pytest.mark.usefixtures("test_accounts")
class TestFetchChecksForRunning:

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

    async def test_dropped_fetch_is_logged_at_debug(self, caplog):
        running = await _run("RUNNING", id="run-dropped")
        mock_patronus = MagicMock()
        mock_patronus.get_run_teamcity_checks = AsyncMock(side_effect=RuntimeError("boom"))

        with caplog.at_level(logging.DEBUG):
            result = await space.patronus.fetch_checks_for_running(mock_patronus, [running])

        assert result == {}
        assert [r.levelname for r in caplog.records if "run-dropped" in r.getMessage()] == ["DEBUG"]
        assert any("boom" in r.getMessage() for r in caplog.records)

    @pytest.mark.raises_unrecognised_api_value
    async def test_strict_error_is_reraised_among_other_results(self, httpx_mock, patronus_client):
        from space.models.enums import UnrecognisedApiValue

        runs = [await _run("RUNNING", id=f"run-{name}") for name in "ABCD"]

        def url(name: str) -> str:
            return f"{patronus_client.base_url}/app/rest/v1/robots/run-{name}/teamcity-checks"

        # A strict failure cancels the other fetches, so theirs may never be requested.
        httpx_mock.add_response(url=url("A"), json={"teamCityChecks": [wire_check("SUCCESS")]}, is_optional=True)
        httpx_mock.add_response(url=url("B"), status_code=500, is_optional=True)
        httpx_mock.add_response(url=url("C"), status_code=503, is_optional=True)
        httpx_mock.add_response(url=url("D"), json={"teamCityChecks": [wire_check("NEW_CHECK_STATUS")]})

        with pytest.raises(UnrecognisedApiValue, match="NEW_CHECK_STATUS"):
            await space.patronus.fetch_checks_for_running(patronus_client, runs)

    async def test_first_never_dropped_error_wins_and_the_rest_are_logged(self, caplog):
        from space.models.enums import UnrecognisedApiValue

        runs = [await _run("RUNNING", id=f"run-{name}") for name in "ABCD"]
        later = UnrecognisedApiValue("CheckStatus", "X")
        effects = {"run-A": _checks("SUCCESS"), "run-B": AssertionError("b"), "run-C": [], "run-D": later}

        async def fetch(run_id):
            effect = effects[run_id]
            if isinstance(effect, BaseException):
                raise effect
            return effect

        mock_patronus = MagicMock()
        mock_patronus.get_run_teamcity_checks = fetch
        with caplog.at_level(logging.DEBUG), pytest.raises(AssertionError, match="^b$"):
            await space.patronus.fetch_checks_for_running(mock_patronus, runs)
        (record, ) = [r for r in caplog.records if r.name == "space.aio"]
        assert record.levelno == logging.DEBUG
        assert record.exc_info is not None and record.exc_info[1] is later

    async def test_never_dropped_failure_cancels_the_other_fetches(self):
        from space.models.enums import UnrecognisedApiValue

        record: list[str] = []
        runs = [await _run("RUNNING", id="run-blocked"), await _run("RUNNING", id="run-strict")]

        async def fetch(run_id):
            if run_id == "run-strict":
                raise UnrecognisedApiValue("CheckStatus", "NEW")
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                record.append("cancelled")
                raise

        mock_patronus = MagicMock()
        mock_patronus.get_run_teamcity_checks = fetch
        with pytest.raises(UnrecognisedApiValue):
            await space.patronus.fetch_checks_for_running(mock_patronus, runs)
        assert record == ["cancelled"]

    async def test_unresolved_error_is_reraised_from_fetches(self):
        from space.models.enums import StrictModeUnresolved

        runs = [await _run("RUNNING", id="run-A")]
        error = StrictModeUnresolved("strict mode was not resolved")
        mock_patronus = MagicMock()
        mock_patronus.get_run_teamcity_checks = AsyncMock(side_effect=error)
        with pytest.raises(StrictModeUnresolved):
            await space.patronus.fetch_checks_for_running(mock_patronus, runs)

    async def test_ordinary_failures_are_still_dropped(self, caplog):
        runs = [await _run("RUNNING", id=f"run-{name}") for name in "ABC"]
        effects = {"run-A": _checks("SUCCESS"), "run-B": RuntimeError("b"), "run-C": ValueError("c")}

        async def fetch(run_id):
            effect = effects[run_id]
            if isinstance(effect, BaseException):
                raise effect
            return effect

        mock_patronus = MagicMock()
        mock_patronus.get_run_teamcity_checks = fetch
        with caplog.at_level(logging.DEBUG):
            result = await space.patronus.fetch_checks_for_running(mock_patronus, runs)
        assert list(result) == ["run-A"]
        for run_id in ("run-B", "run-C"):
            (record, ) = [r for r in caplog.records if run_id in r.getMessage()]
            assert record.levelname == "DEBUG" and record.exc_info is not None

    async def test_cancelled_fetch_is_not_dropped(self):
        # A cancellation is not a failed fetch: it cancels the other fetches and propagates.
        record: list[str] = []
        runs = [await _run("RUNNING", id="run-cancelled"), await _run("RUNNING", id="run-blocked")]

        async def fetch(run_id):
            if run_id == "run-cancelled":
                raise asyncio.CancelledError
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                record.append("cancelled")
                raise

        mock_patronus = MagicMock()
        mock_patronus.get_run_teamcity_checks = fetch
        with pytest.raises(asyncio.CancelledError):
            await space.patronus.fetch_checks_for_running(mock_patronus, runs)
        assert record == ["cancelled"]
