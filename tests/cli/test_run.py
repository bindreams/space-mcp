"""Tests for CLI run commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from tests.factories import make_mr

from .conftest import run_cli


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
