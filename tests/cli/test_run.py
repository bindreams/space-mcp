"""Tests for CLI run commands."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import click
import pytest

from space.models import SafeMergeStart
from tests.factories import make_mr
from tests.sample_responses import SAMPLE_ATTEMPT_DETAILS, wire_attempt, wire_check, wire_run

from .conftest import RUN_ID, mock_run_responses, patronus_url, run_cli

_ENV = {"SPACE_TOKEN": "test"}


def _header_line(output: str) -> str:
    """The `run view` status header, e.g. `RUNNING — DRY_RUN`."""
    return next(line for line in output.splitlines() if line.endswith("— DRY_RUN"))


class TestRunList:

    def test_help(self):
        result = run_cli("run", "list", "--help")
        assert result.exit_code == 0
        assert "--branch" in result.output
        assert "--base" in result.output

    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.patronus.PatronusClient.list_runs")
    @patch("space.client.SpaceClient.find_merge_request_by_branch", return_value=None)
    @patch("space.context.detect_git_context")
    def test_list_empty(self, mock_ctx, mock_find, mock_list, mock_token):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="ij", repo="ultimate", branch="main")
        mock_list.return_value = []
        result = run_cli("run", "list", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        assert "No Patronus runs found" in result.output


class TestRunStart:

    @patch("space.cli.run.resolve_mr_with_project")
    @patch("space.client.SpaceClient.start_safe_merge", new_callable=AsyncMock)
    def test_start_targets_ref_project_not_state_project(self, mock_merge, mock_resolve):
        # The ref resolves to a different project than SPACE_PROJECT; the safe-merge
        # must target the ref's project (review numbers are per-project).
        mock_resolve.return_value = (make_mr(number=42), "OTHERPROJ")
        mock_merge.return_value = SafeMergeStart(run_id="r1", status="InProgress")
        result = run_cli(
            "run",
            "start",
            "42",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code == 0
        assert mock_merge.await_args.kwargs["project"] == "OTHERPROJ"


class TestRunCancel:

    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.patronus.PatronusClient.cancel_run")
    @patch("space.context.detect_git_context")
    def test_cancel(self, mock_ctx, mock_cancel, mock_token):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="ij", repo="ultimate", branch="main")
        mock_cancel.return_value = None
        result = run_cli("run", "cancel", "cc448634-880e-411f-9ee6-347e9a6087ac", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        assert "Cancelled" in result.output
        mock_cancel.assert_called_once_with("cc448634-880e-411f-9ee6-347e9a6087ac")


class TestRunViewStatuses:

    def test_view_running_run_with_queued_check_shows_running(self, httpx_mock, test_accounts):
        mock_run_responses(httpx_mock, wire_run("RUNNING"), [wire_check("QUEUED")], problems=True)

        result = run_cli("run", "view", RUN_ID, env=_ENV)

        assert result.exit_code == 0
        assert _header_line(result.output) == "RUNNING — DRY_RUN"
        assert "UNKNOWN" not in result.output

    def test_view_running_run_with_canceled_check_shows_running(self, httpx_mock, test_accounts):
        mock_run_responses(httpx_mock, wire_run("RUNNING"), [wire_check("CANCELED")], problems=True)

        result = run_cli("run", "view", RUN_ID, env=_ENV)

        assert _header_line(result.output) == "RUNNING — DRY_RUN"
        assert "UNKNOWN" not in result.output

    def test_view_json_reports_wire_statuses(self, httpx_mock, test_accounts):
        mock_run_responses(
            httpx_mock, wire_run("RUNNING"), [wire_check("QUEUED", attempts=[wire_attempt("RUNNING")])], problems=True
        )

        result = run_cli("--json", "", "run", "view", RUN_ID, env=_ENV)

        data = json.loads(result.output)
        assert data["run"]["status"] == "RUNNING"
        assert data["checks"][0]["status"] == "QUEUED"
        assert data["checks"][0]["attempts"][0]["status"] == "RUNNING"

    def test_view_lists_failed_tests_for_failed_attempt(self, httpx_mock, test_accounts):
        failed = wire_check("FAILURE", attempts=[wire_attempt("FAILURE", "attempt-fail-1")])
        mock_run_responses(httpx_mock, wire_run("FAILURE"), [failed], problems=True)
        httpx_mock.add_response(
            url=patronus_url("/app/rest/v1/teamcity-checks/attempts/attempt-fail-1"),
            json=SAMPLE_ATTEMPT_DETAILS,
        )

        result = run_cli("run", "view", RUN_ID, env=_ENV)

        assert "Failed tests in" in result.output
        assert "com.example.FooTest.test something important" in result.output
        assert httpx_mock.get_requests(url=patronus_url("/app/rest/v1/teamcity-checks/attempts/attempt-fail-1"))


class TestRunViewCheckSummary:

    def test_view_check_summary_counts_queued_canceled_skipped(self, httpx_mock, test_accounts):
        checks = [
            wire_check("SKIPPED", "a"),
            wire_check("CANCELED", "b"),
            wire_check("QUEUED", "c"),
            wire_check("RUNNING", "d"),
            wire_check("FAILURE", "e"),
            wire_check("SUCCESS", "f"),
        ]
        mock_run_responses(httpx_mock, wire_run("RUNNING"), checks, problems=True)

        result = run_cli("run", "view", RUN_ID, env=_ENV)

        assert (
            "TeamCity Checks (6 total: 1 success, 1 failure, 1 running, 1 queued, 1 canceled, 1 skipped)"
            in result.output
        )


class TestRunListStatuses:

    @patch("space.client.SpaceClient.find_merge_request_by_branch", return_value=None)
    @patch("space.context.detect_git_context")
    def test_list_running_run_with_queued_check_shows_running(self, mock_ctx, mock_find, httpx_mock, test_accounts):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="ij", repo="ultimate", branch="feat")
        httpx_mock.add_response(
            url=patronus_url("/app/rest/v1/robots"),
            match_params={"sourceBranch": "feat"},
            json={"robots": [wire_run("RUNNING")]},
        )
        httpx_mock.add_response(
            url=patronus_url(f"/app/rest/v1/robots/{RUN_ID}/teamcity-checks"),
            json={"robotId": RUN_ID, "teamCityChecks": [wire_check("QUEUED")]},
        )

        result = run_cli("run", "list", env=_ENV)

        row = next(line for line in result.output.splitlines() if "refs/patronus" in line)
        assert row.split()[0] == "RUNNING"
        assert "UNKNOWN" not in result.output


class TestRunWatchStatuses:

    def test_watch_header_running_run_with_queued_check_shows_running(self, httpx_mock, test_accounts):
        # A running run keeps the watch polling.
        mock_run_responses(httpx_mock, wire_run("RUNNING"), [wire_check("QUEUED")])
        mock_run_responses(httpx_mock, wire_run("SUCCESS"), [wire_check("SUCCESS")])

        result = run_cli("run", "watch", RUN_ID, "-i", "0", env=_ENV)

        headers = [line for line in result.output.splitlines() if "(cc448634-880...)" in line]
        assert [h.rsplit("[", 1)[1] for h in headers] == ["RUNNING]", "SUCCESS]"]


def test_json_serialises_status_as_value(capsys):
    from space.cli import format as fmt
    from space.models import RunStatus
    from tests.factories import make_run

    fmt.print_json(make_run(status=RunStatus.SUCCESS))

    assert '"status": "SUCCESS"' in capsys.readouterr().out


class TestRunWatchCanceling:

    def test_watch_polls_canceling_until_canceled(self, httpx_mock, test_accounts):
        mock_run_responses(httpx_mock, wire_run("CANCELING"), [wire_check("RUNNING")])
        mock_run_responses(httpx_mock, wire_run("CANCELED"), [wire_check("CANCELED")])

        result = run_cli("run", "watch", RUN_ID, "-i", "0", env=_ENV)

        assert result.exit_code == 0
        assert len(httpx_mock.get_requests(url=patronus_url(f"/app/rest/v1/robots/{RUN_ID}"))) == 2

    def test_watch_does_not_fail_fast_on_canceling_run(self, httpx_mock, test_accounts):
        mock_run_responses(httpx_mock, wire_run("CANCELING"), [wire_check("FAILURE")])
        mock_run_responses(httpx_mock, wire_run("CANCELED"), [wire_check("CANCELED")])

        result = run_cli("run", "watch", RUN_ID, "-i", "0", env=_ENV)

        assert result.exit_code == 0
        assert len(httpx_mock.get_requests(url=patronus_url(f"/app/rest/v1/robots/{RUN_ID}"))) == 2
        assert "Run is failing" not in result.output


class TestRunWatchFailFast:

    def test_watch_fails_fast_on_running_run_with_failed_check(self, httpx_mock, test_accounts):
        mock_run_responses(httpx_mock, wire_run("RUNNING"), [wire_check("FAILURE"), wire_check("RUNNING")])

        result = run_cli("run", "watch", RUN_ID, "-i", "0", env=_ENV)

        assert result.exit_code == 1
        assert "Run is failing" in result.output

    def test_watch_no_fail_fast_keeps_polling(self, httpx_mock, test_accounts):
        mock_run_responses(httpx_mock, wire_run("RUNNING"), [wire_check("FAILURE"), wire_check("RUNNING")])
        mock_run_responses(httpx_mock, wire_run("FAILURE"), [wire_check("FAILURE"), wire_check("CANCELED")])

        result = run_cli("run", "watch", RUN_ID, "-i", "0", "--no-fail-fast", env=_ENV)

        assert "Run is failing" not in result.output
        assert len(httpx_mock.get_requests(url=patronus_url(f"/app/rest/v1/robots/{RUN_ID}"))) == 2


class TestRunWatchSummary:

    @pytest.mark.unrecognised_api_value
    def test_watch_summary_buckets(self, httpx_mock, test_accounts):
        checks = [
            wire_check("SUCCESS", "a"),
            wire_check("QUEUED", "b"),
            wire_check("CANCELED", "c"),
            wire_check("SKIPPED", "d"),
            wire_check("TASK3_UNMODELLED", "e"),
        ]
        mock_run_responses(httpx_mock, wire_run("CANCELED"), checks)

        result = run_cli("--no-strict", "run", "watch", RUN_ID, "-i", "0", env=_ENV)

        assert "1 passed · 1 queued · 1 canceled · 1 skipped · 1 other" in result.output
        assert "⊘ c" in result.output
        assert "– d" in result.output

    @pytest.mark.unrecognised_api_value
    def test_watch_on_unrecognised_run_status_says_so(self, httpx_mock, test_accounts):
        mock_run_responses(httpx_mock, wire_run("TASK3_UNMODELLED"), [wire_check("SUCCESS")])

        result = run_cli("--no-strict", "run", "watch", RUN_ID, "-i", "0", env=_ENV)

        assert result.exit_code == 0
        assert "Run status is unrecognised (UNKNOWN); stopping the watch." in result.output


class TestRunFetchSiblings:
    """A failed run fetch cancels and awaits its siblings before the CLI closes its clients."""

    @pytest.mark.raises_unrecognised_api_value
    @pytest.mark.parametrize("command", ["watch", "view"])
    def test_failed_fetch_cancels_its_sibling_before_cleanup(self, httpx_mock, test_accounts, monkeypatch, command):
        import asyncio

        from space.patronus import PatronusClient

        record: list[str] = []

        async def gated(request):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                record.append("sibling cancelled")
                raise

        original_aclose = PatronusClient.aclose

        async def aclose(self):
            record.append("aclose")
            await original_aclose(self)

        monkeypatch.setattr(PatronusClient, "aclose", aclose)
        httpx_mock.add_response(url=patronus_url(f"/app/rest/v1/robots/{RUN_ID}"), json=wire_run("NEW_STATUS"))
        httpx_mock.add_callback(gated, url=patronus_url(f"/app/rest/v1/robots/{RUN_ID}/teamcity-checks"))
        siblings = 1
        if command == "view":
            httpx_mock.add_callback(gated, url=patronus_url(f"/app/rest/v1/robots/{RUN_ID}/problems"))
            siblings = 2
        args = ["run", "watch", RUN_ID, "-i", "0"] if command == "watch" else ["run", "view", RUN_ID]

        result = run_cli(*args, env=_ENV)

        assert result.exit_code == 1
        assert "Error: RunStatus: unrecognised value 'NEW_STATUS' (strict mode)" in result.output
        assert record == ["sibling cancelled"] * siblings + ["aclose"]

    @pytest.mark.raises_unrecognised_api_value
    def test_both_failed_fetches_are_retrieved(self, httpx_mock, test_accounts, caplog, monkeypatch):
        import asyncio
        import gc
        import logging

        import httpx

        from space.patronus import PatronusClient

        # The checks response waits for get_run to fail, so get_run completes first and the checks failure, which
        # asyncio.wait(FIRST_EXCEPTION) leaves unretrieved as the last completion, is the one under test.
        run_failed = asyncio.Event()
        original_get_run = PatronusClient.get_run

        async def get_run(self, run_id):
            try:
                return await original_get_run(self, run_id)
            finally:
                run_failed.set()

        async def checks(request):
            await run_failed.wait()
            return httpx.Response(200, json={"robotId": RUN_ID, "teamCityChecks": [wire_check("NEW_CHECK_STATUS")]})

        monkeypatch.setattr(PatronusClient, "get_run", get_run)
        httpx_mock.add_response(url=patronus_url(f"/app/rest/v1/robots/{RUN_ID}"), json=wire_run("NEW_STATUS"))
        httpx_mock.add_callback(checks, url=patronus_url(f"/app/rest/v1/robots/{RUN_ID}/teamcity-checks"))

        assert run_cli("run", "watch", RUN_ID, "-i", "0", env=_ENV).exit_code == 1  # no binding: see gc.collect()
        gc.collect()

        assert [r for r in caplog.records if r.name == "asyncio" and r.levelno >= logging.ERROR] == []


class TestRunStartWatch:

    _POST = "https://jetbrains.team/api/http/projects/key:ij/code-reviews/safe-merge"

    @pytest.mark.parametrize(
        ("get_run", "cause"),
        [
            ("500", "HTTP 500"),
            pytest.param(
                "strict",
                "RunStatus: unrecognised value 'NEW_STATUS' (strict mode)",
                marks=pytest.mark.raises_unrecognised_api_value,
            ),
        ],
    )
    def test_run_start_watch_failure_says_run_started(self, httpx_mock, test_accounts, get_run, cause):
        httpx_mock.add_response(url=self._POST, json={"robotId": RUN_ID, "status": "RUNNING"})
        run_url = patronus_url(f"/app/rest/v1/robots/{RUN_ID}")
        if get_run == "500":
            httpx_mock.add_response(url=run_url, status_code=500)
        else:
            httpx_mock.add_response(url=run_url, json=wire_run("NEW_STATUS"))
        httpx_mock.add_response(
            url=f"{run_url}/teamcity-checks", json={"robotId": RUN_ID, "teamCityChecks": []}, is_optional=True
        )

        with patch("space.cli.run.resolve_mr_with_project", return_value=(make_mr(number=42, id="4Xa1b2"), "ij")):
            result = run_cli("run", "start", "42", "--watch", env={**_ENV, "SPACE_PROJECT": "ij", "SPACE_REPO": "r"})

        assert result.exit_code == 1
        assert f"Run ID: {RUN_ID}" in result.output
        assert f"Error: run {RUN_ID} was started, but watching it failed: {cause}" in result.output
        watch = "space --no-strict run watch" if get_run == "strict" else "space run watch"
        assert f"The run was started; do not re-run it. Watch it with `{watch} {RUN_ID}`." in result.output
        assert "Run as" not in result.output

    def test_run_start_fail_fast_still_exits_1(self, httpx_mock, test_accounts):
        httpx_mock.add_response(url=self._POST, json={"robotId": RUN_ID, "status": "RUNNING"})
        mock_run_responses(httpx_mock, wire_run("RUNNING"), [wire_check("FAILURE")])

        with patch("space.cli.run.resolve_mr_with_project", return_value=(make_mr(number=42, id="4Xa1b2"), "ij")):
            result = run_cli("run", "start", "42", "--watch", env={**_ENV, "SPACE_PROJECT": "ij", "SPACE_REPO": "r"})

        assert result.exit_code == 1
        assert "watching it failed" not in result.output
        assert result.output.splitlines(
        )[-1] == ("Run is failing (1 check(s) failed). Use --no-fail-fast to watch to completion.")


class TestRunStartWatchDispositions:
    """The run ID is printed before watching; what the watch raises decides how it surfaces."""

    _POST = "https://jetbrains.team/api/http/projects/key:ij/code-reviews/safe-merge"
    _ENV = {"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "r"}

    def _invoke(self, httpx_mock, watch_error):
        from click.testing import CliRunner

        from space.__main__ import main

        httpx_mock.add_response(url=self._POST, json={"robotId": RUN_ID, "status": "RUNNING"})
        with patch("space.cli.run.resolve_mr_with_project", return_value=(make_mr(number=42, id="4Xa1b2"), "ij")), \
                patch("space.cli.run._watch_run", AsyncMock(side_effect=watch_error)):
            return CliRunner().invoke(main, ["run", "start", "42", "--watch"], env=self._ENV, catch_exceptions=True)

    def test_assertion_is_not_wrapped(self, httpx_mock):
        error = AssertionError("contract")
        result = self._invoke(httpx_mock, error)
        assert result.exception is error
        assert f"Run ID: {RUN_ID}" in result.output
        assert "watching it failed" not in result.output

    @pytest.mark.parametrize(
        ("error", "exit_code", "text"),
        [
            (click.ClickException("stop"), 1, "Error: stop"),
            (click.exceptions.Exit(3), 3, None),
            (click.Abort(), 1, "Aborted!"),
        ],
        ids=["click-exception", "exit", "abort"],
    )
    def test_click_exits_are_not_wrapped(self, httpx_mock, error, exit_code, text):
        result = self._invoke(httpx_mock, error)
        assert result.exit_code == exit_code
        assert f"Run ID: {RUN_ID}" in result.output
        assert "watching it failed" not in result.output
        if text is not None:
            assert text in result.output

    def test_other_failure_is_wrapped_and_logged(self, httpx_mock, caplog):
        import logging

        error = RuntimeError("boom")
        with caplog.at_level(logging.DEBUG):
            result = self._invoke(httpx_mock, error)
        assert result.exit_code == 1
        assert f"Error: run {RUN_ID} was started, but watching it failed: boom" in result.output
        (record, ) = [r for r in caplog.records if "watching run" in r.getMessage()]
        assert record.levelno == logging.DEBUG
        assert record.exc_info is not None and record.exc_info[1] is error
