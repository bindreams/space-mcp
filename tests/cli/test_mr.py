"""Tests for CLI MR commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import httpx

from tests.factories import make_mr

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

    @patch("space.cli.mr.resolve_mr")
    def test_view_by_number(self, mock_resolve):
        mock_resolve.return_value = make_mr()
        result = run_cli(
            "mr", "view", "188120", env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"}
        )
        assert result.exit_code == 0
        assert "#188120" in result.output
        assert "Fix authentication bug" in result.output
        assert "Opened" in result.output
        assert "John Doe" in result.output

    @patch("space.cli.mr.resolve_mr")
    def test_view_json(self, mock_resolve):
        mock_resolve.return_value = make_mr(title="Fix auth", participants=(), branch_pair=None)
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
