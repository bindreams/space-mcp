"""Tests for CLI run commands."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

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
        mock_merge.return_value = {"robotId": "r1", "status": "InProgress"}
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
        # regression guard: passes before and after the status-enum change
        failed = wire_check("FAILURE", attempts=[wire_attempt("FAILURE", "attempt-fail-1")])
        mock_run_responses(httpx_mock, wire_run("FAILURE"), [failed], problems=True)
        httpx_mock.add_response(
            url=patronus_url("/app/rest/v1/teamcity-checks/attempts/attempt-fail-1"),
            json=SAMPLE_ATTEMPT_DETAILS,
        )

        result = run_cli("run", "view", RUN_ID, env=_ENV)

        assert "Failed tests in" in result.output


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
        # A running run keeps the watch polling: the first pair is RUNNING, the second SUCCESS.
        mock_run_responses(httpx_mock, wire_run("RUNNING"), [wire_check("QUEUED")])
        mock_run_responses(httpx_mock, wire_run("SUCCESS"), [wire_check("SUCCESS")])

        result = run_cli("run", "watch", RUN_ID, "-i", "0", env=_ENV)

        headers = [line for line in result.output.splitlines() if "(cc448634-880...)" in line]
        assert [h.rsplit("[", 1)[1] for h in headers] == ["RUNNING]", "SUCCESS]"]
