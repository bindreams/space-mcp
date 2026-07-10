"""Tests for CLI MR commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import httpx

from tests.factories import make_mr
from space.client import AuthorNotFoundError

from .conftest import run_cli


async def _async_gen_from(items):
    """Create an async generator yielding the given items."""
    for item in items:
        yield item


class TestMrView:

    def test_help(self):
        result = run_cli("mr", "view", "--help")
        assert result.exit_code == 0
        assert "MR_REF" in result.output
        assert "--web" in result.output

    @patch("space.cli.mr.resolve_mr_with_project")
    def test_view_by_number(self, mock_resolve):
        mock_resolve.return_value = (make_mr(), "ij")
        result = run_cli(
            "mr", "view", "188120", env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"}
        )
        assert result.exit_code == 0
        assert "#188120" in result.output
        assert "Fix authentication bug" in result.output
        assert "Opened" in result.output
        assert "John Doe" in result.output

    @patch("space.cli.mr.resolve_mr_with_project")
    def test_view_json(self, mock_resolve):
        mock_resolve.return_value = (make_mr(title="Fix auth", participants=(), branch_pair=None), "ij")
        result = run_cli(
            "--json",
            "",
            "mr",
            "view",
            "188120",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"}
        )
        assert result.exit_code == 0
        assert '"number": 188120' in result.output

    @patch("space.cli.mr.click.launch")
    @patch("space.cli.mr.resolve_mr_with_project")
    def test_view_web_targets_ref_project_not_state_project(self, mock_resolve, mock_launch):
        # The ref resolves to a different project than SPACE_PROJECT; the browser URL must
        # point at the ref's project (review numbers are per-project).
        mock_resolve.return_value = (make_mr(number=42), "OTHERPROJ")
        result = run_cli(
            "mr",
            "view",
            "42",
            "--web",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code == 0
        mock_launch.assert_called_once()
        url = mock_launch.call_args.args[0]
        assert "/p/OTHERPROJ/reviews/42/" in url
        assert "/p/ij/" not in url


class TestMrList:

    def test_help(self):
        result = run_cli("mr", "list", "--help")
        assert result.exit_code == 0
        assert "--state" in result.output
        assert "--limit" in result.output

    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.list_merge_requests")
    @patch("space.context.detect_git_context")
    def test_list_empty(self, mock_ctx, mock_list, mock_token):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="ij", repo="ultimate", branch="main")
        mock_list.return_value = _async_gen_from([])
        result = run_cli("mr", "list", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        assert "No merge requests found" in result.output

    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.list_merge_requests")
    @patch("space.context.detect_git_context")
    def test_mr_list_passes_author_to_client(self, mock_ctx, mock_list, mock_token):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="ij", repo="ultimate", branch="main")
        mock_list.return_value = _async_gen_from([make_mr()])
        result = run_cli("mr", "list", "--author", "azhukova", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        mock_list.assert_called_once()
        call_kwargs = mock_list.call_args[1]
        assert call_kwargs["author"] == "azhukova"

    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.list_merge_requests")
    @patch("space.context.detect_git_context")
    def test_list_unresolvable_author_clean_error(self, mock_ctx, mock_list, mock_token):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="ij", repo="ultimate", branch="main")

        async def _raises(**kw):
            raise AuthorNotFoundError("No Space user found for author 'no.such.user'.")
            yield  # async generator

        mock_list.return_value = _raises()
        result = run_cli("mr", "list", "--author", "no.such.user", env={"SPACE_TOKEN": "test"})
        assert result.exit_code != 0
        assert "No Space user found for author 'no.such.user'." in result.output

    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.list_merge_requests")
    @patch("space.context.detect_git_context")
    def test_list_with_results(self, mock_ctx, mock_list, mock_token):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="ij", repo="ultimate", branch="main")
        mock_list.return_value = _async_gen_from([make_mr(id="123", title="Fix bug", number=123)])
        result = run_cli("mr", "list", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        assert "Fix bug" in result.output
        assert "Opened" in result.output


class TestMrDelete:

    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.set_merge_request_state", new_callable=AsyncMock)
    @patch("space.context.detect_git_context")
    def test_delete_single_mr(self, mock_ctx, mock_state, mock_token):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="proj", repo="test", branch="main")
        result = run_cli("mr", "delete", "42", "--yes", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        mock_state.assert_called_once_with("proj", "42", "Deleted")
        assert "Deleted 1" in result.output

    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.set_merge_request_state", new_callable=AsyncMock)
    @patch("space.context.detect_git_context")
    def test_delete_multiple_mrs(self, mock_ctx, mock_state, mock_token):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="proj", repo="test", branch="main")
        result = run_cli("mr", "delete", "1", "2", "3", "--yes", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        assert mock_state.call_count == 3

    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.set_merge_request_state", new_callable=AsyncMock)
    @patch("space.context.detect_git_context")
    def test_delete_continues_on_error(self, mock_ctx, mock_state, mock_token):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="proj", repo="test", branch="main")
        mock_state.side_effect = [
            None,
            httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock(status_code=404)),
            None,
        ]
        result = run_cli("mr", "delete", "1", "2", "3", "--yes", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        assert mock_state.call_count == 3
        assert "failed" in result.output.lower() or "error" in result.output.lower()

    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.set_merge_request_state", new_callable=AsyncMock)
    @patch("space.context.detect_git_context")
    def test_delete_yes_flag_skips_confirmation(self, mock_ctx, mock_state, mock_token):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="proj", repo="test", branch="main")
        result = run_cli("mr", "delete", "42", "--yes", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        mock_state.assert_called_once()


class TestMrEdit:

    def test_help(self):
        result = run_cli("mr", "edit", "--help")
        assert result.exit_code == 0
        assert "--title" in result.output
        assert "--description" in result.output

    @patch("space.cli.mr_actions.resolve_mr_with_project")
    @patch("space.client.SpaceClient.edit_merge_request", new_callable=AsyncMock)
    def test_edit_title(self, mock_edit, mock_resolve):
        mock_resolve.return_value = (make_mr(number=42), "ij")
        mock_edit.return_value = make_mr(number=42, title="New title")
        result = run_cli(
            "mr",
            "edit",
            "42",
            "-t",
            "New title",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code == 0
        mock_edit.assert_awaited_once_with("ij", "42", title="New title", description=None)
        assert "Updated #42" in result.output
        assert "title" in result.output and "New title" in result.output

    @patch("space.cli.mr_actions.resolve_mr_with_project")
    @patch("space.client.SpaceClient.edit_merge_request", new_callable=AsyncMock)
    def test_edit_description_only(self, mock_edit, mock_resolve):
        mock_resolve.return_value = (make_mr(number=42), "ij")
        mock_edit.return_value = make_mr(number=42)
        result = run_cli(
            "mr",
            "edit",
            "42",
            "-d",
            "D",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code == 0
        mock_edit.assert_awaited_once_with("ij", "42", title=None, description="D")
        assert "description updated" in result.output
        assert "title" not in result.output.lower()

    @patch("space.cli.mr_actions.resolve_mr_with_project")
    @patch("space.client.SpaceClient.edit_merge_request", new_callable=AsyncMock)
    def test_edit_clear_description(self, mock_edit, mock_resolve):
        mock_resolve.return_value = (make_mr(number=42), "ij")
        mock_edit.return_value = make_mr(number=42)
        result = run_cli(
            "mr",
            "edit",
            "42",
            "-d",
            "",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code == 0
        mock_edit.assert_awaited_once_with("ij", "42", title=None, description="")
        assert "description cleared" in result.output

    @patch("space.cli.mr_actions.resolve_mr_with_project")
    @patch("space.client.SpaceClient.edit_merge_request", new_callable=AsyncMock)
    def test_edit_both_fields(self, mock_edit, mock_resolve):
        mock_resolve.return_value = (make_mr(number=42), "ij")
        mock_edit.return_value = make_mr(number=42, title="T")
        result = run_cli(
            "mr",
            "edit",
            "42",
            "-t",
            "T",
            "-d",
            "D",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code == 0
        mock_edit.assert_awaited_once_with("ij", "42", title="T", description="D")
        assert "description updated" in result.output

    @patch("space.cli.mr_actions.resolve_mr_with_project")
    @patch("space.client.SpaceClient.edit_merge_request", new_callable=AsyncMock)
    def test_edit_json_output(self, mock_edit, mock_resolve):
        mock_resolve.return_value = (make_mr(number=42), "ij")
        mock_edit.return_value = make_mr(number=42, title="New title", participants=(), branch_pair=None)
        result = run_cli(
            "--json",
            "",
            "mr",
            "edit",
            "42",
            "-t",
            "New title",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code == 0
        assert '"number": 42' in result.output
        assert "Updated #42" not in result.output  # JSON branch only, no human text

    @patch("space.cli.mr_actions.resolve_mr_with_project")
    @patch("space.client.SpaceClient.edit_merge_request", new_callable=AsyncMock)
    def test_edit_partial_failure_reports_cleanly(self, mock_edit, mock_resolve):
        from space.client import MergeRequestEditError
        mock_resolve.return_value = (make_mr(number=42), "ij")
        mock_edit.side_effect = MergeRequestEditError(["title"], RuntimeError("boom"))
        result = run_cli(
            "mr",
            "edit",
            "42",
            "-t",
            "T",
            "-d",
            "D",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code != 0
        assert "title" in result.output  # honest: names the applied field
        assert "Traceback" not in result.output  # clean ClickException, not a crash

    @patch("space.cli.mr_actions.resolve_mr_with_project")
    @patch("space.client.SpaceClient.edit_merge_request", new_callable=AsyncMock)
    def test_edit_no_options_errors(self, mock_edit, mock_resolve):
        result = run_cli(
            "mr",
            "edit",
            "42",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code != 0
        assert "title" in result.output.lower() and "description" in result.output.lower()
        mock_edit.assert_not_called()
        mock_resolve.assert_not_called()

    @patch("space.cli.mr_actions.resolve_mr_with_project")
    @patch("space.client.SpaceClient.edit_merge_request", new_callable=AsyncMock)
    def test_edit_targets_ref_project_not_state_project(self, mock_edit, mock_resolve):
        # The ref resolves to a different project than SPACE_PROJECT; the edit must
        # PATCH against the ref's project (review numbers are per-project).
        mock_resolve.return_value = (make_mr(number=42), "OTHERPROJ")
        mock_edit.return_value = make_mr(number=42, title="X")
        result = run_cli(
            "mr",
            "edit",
            "42",
            "-t",
            "X",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code == 0
        mock_edit.assert_awaited_once_with("OTHERPROJ", "42", title="X", description=None)


class TestMrTimeline:

    @patch("space.cli.mr.resolve_mr_with_project")
    @patch("space.client.SpaceClient.get_merge_request_discussions", new_callable=AsyncMock)
    def test_timeline_targets_ref_project_not_state_project(self, mock_discussions, mock_resolve):
        # The ref resolves to a different project than SPACE_PROJECT; the timeline must
        # be fetched against the ref's project (review numbers are per-project).
        mock_resolve.return_value = (make_mr(number=42), "OTHERPROJ")
        mock_discussions.return_value = []
        result = run_cli(
            "mr",
            "timeline",
            "42",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code == 0
        assert mock_discussions.await_args.args[0] == "OTHERPROJ"


class TestMrChecks:

    @patch("space.cli.mr.resolve_mr_with_project")
    @patch("space.patronus.PatronusClient.list_runs_for_review", new_callable=AsyncMock)
    def test_checks_targets_ref_project_not_state_project(self, mock_runs, mock_resolve):
        # The ref resolves to a different project than SPACE_PROJECT; Patronus runs must
        # be queried against the ref's project (review numbers are per-project).
        mock_resolve.return_value = (make_mr(number=42), "OTHERPROJ")
        mock_runs.return_value = []
        result = run_cli(
            "mr",
            "checks",
            "42",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code == 0
        assert mock_runs.await_args.args[0] == "OTHERPROJ"


class TestMrClose:

    @patch("space.cli.mr_actions.resolve_mr_with_project")
    @patch("space.client.SpaceClient.set_merge_request_state", new_callable=AsyncMock)
    def test_close_targets_ref_project_not_state_project(self, mock_state, mock_resolve):
        mock_resolve.return_value = (make_mr(number=42), "OTHERPROJ")
        result = run_cli(
            "mr",
            "close",
            "42",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code == 0
        mock_state.assert_awaited_once_with("OTHERPROJ", "42", "Closed")


class TestMrReopen:

    @patch("space.cli.mr_actions.resolve_mr_with_project")
    @patch("space.client.SpaceClient.set_merge_request_state", new_callable=AsyncMock)
    def test_reopen_targets_ref_project_not_state_project(self, mock_state, mock_resolve):
        mock_resolve.return_value = (make_mr(number=42), "OTHERPROJ")
        result = run_cli(
            "mr",
            "reopen",
            "42",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code == 0
        mock_state.assert_awaited_once_with("OTHERPROJ", "42", "Opened")


class TestMrMerge:

    @patch("space.cli.mr_actions.resolve_mr_with_project")
    @patch("space.client.SpaceClient.start_safe_merge", new_callable=AsyncMock)
    def test_merge_targets_ref_project_not_state_project(self, mock_merge, mock_resolve):
        mock_resolve.return_value = (make_mr(number=42), "OTHERPROJ")
        mock_merge.return_value = {"robotId": "r1", "status": "InProgress"}
        result = run_cli(
            "mr",
            "merge",
            "42",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code == 0
        assert mock_merge.await_args.kwargs["project"] == "OTHERPROJ"


class TestMrComment:

    @patch("space.cli.mr_actions.resolve_mr_with_project")
    @patch("space.client.SpaceClient.post_comment", new_callable=AsyncMock)
    def test_comment_targets_ref_project_not_state_project(self, mock_comment, mock_resolve):
        mock_resolve.return_value = (make_mr(number=42), "OTHERPROJ")
        mock_comment.return_value = "msg-1"
        result = run_cli(
            "mr",
            "comment",
            "42",
            "Hello",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code == 0
        assert mock_comment.await_args.args[0] == "OTHERPROJ"


class TestMrDiscuss:

    @patch("space.cli.mr_actions.resolve_mr_with_project")
    @patch("space.client.SpaceClient.create_code_discussion", new_callable=AsyncMock)
    def test_discuss_targets_ref_project_not_state_project(self, mock_discuss, mock_resolve):
        mock_resolve.return_value = (make_mr(number=42), "OTHERPROJ")
        mock_discuss.return_value = "channel-1"
        result = run_cli(
            "mr",
            "discuss",
            "42",
            "Look here",
            "--file",
            "a.py",
            "--line",
            "10",
            "--revision",
            "abc123",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code == 0
        assert mock_discuss.await_args.args[0] == "OTHERPROJ"
