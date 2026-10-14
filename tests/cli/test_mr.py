"""Tests for CLI MR commands."""

from __future__ import annotations

import copy
import json
import re
from unittest.mock import AsyncMock, patch, MagicMock
from urllib.parse import urlparse

import click
import httpx
import pytest

from tests.factories import make_mr
from tests.sample_responses import SAMPLE_MERGE_REQUEST
from space.client import AuthorNotFoundError
from space.models import ReviewRef

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

    @patch("space.cli.mr_actions.resolve_mr_with_project", new_callable=AsyncMock)
    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.set_merge_request_state", new_callable=AsyncMock)
    @patch("space.context.detect_git_context")
    def test_delete_single_mr(self, mock_ctx, mock_state, mock_token, mock_resolve):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="proj", repo="test", branch="main")
        mock_resolve.side_effect = [(make_mr(number=42), "proj")]
        result = run_cli("mr", "delete", "42", "--yes", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        mock_state.assert_called_once_with("proj", ReviewRef(number=42), "Deleted")
        assert "Deleted 1" in result.output

    @patch("space.cli.mr_actions.resolve_mr_with_project", new_callable=AsyncMock)
    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.set_merge_request_state", new_callable=AsyncMock)
    @patch("space.context.detect_git_context")
    def test_delete_multiple_mrs(self, mock_ctx, mock_state, mock_token, mock_resolve):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="proj", repo="test", branch="main")
        mock_resolve.side_effect = [
            (make_mr(number=1), "proj"),
            (make_mr(number=2), "proj"),
            (make_mr(number=3), "proj"),
        ]
        result = run_cli("mr", "delete", "1", "2", "3", "--yes", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        assert mock_state.call_count == 3

    @patch("space.cli.mr_actions.resolve_mr_with_project", new_callable=AsyncMock)
    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.set_merge_request_state", new_callable=AsyncMock)
    @patch("space.context.detect_git_context")
    def test_delete_continues_on_error(self, mock_ctx, mock_state, mock_token, mock_resolve):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="proj", repo="test", branch="main")
        mock_resolve.side_effect = [
            (make_mr(number=1), "proj"),
            (make_mr(number=2), "proj"),
            (make_mr(number=3), "proj"),
        ]
        mock_state.side_effect = [
            None,
            httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock(status_code=404)),
            None,
        ]
        result = run_cli("mr", "delete", "1", "2", "3", "--yes", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        assert mock_state.call_count == 3
        assert "failed" in result.output.lower() or "error" in result.output.lower()

    @patch("space.cli.mr_actions.resolve_mr_with_project", new_callable=AsyncMock)
    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.set_merge_request_state", new_callable=AsyncMock)
    @patch("space.context.detect_git_context")
    def test_delete_yes_flag_skips_confirmation(self, mock_ctx, mock_state, mock_token, mock_resolve):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="proj", repo="test", branch="main")
        mock_resolve.side_effect = [(make_mr(number=42), "proj")]
        result = run_cli("mr", "delete", "42", "--yes", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        mock_state.assert_called_once()

    @patch("space.cli.mr_actions.resolve_mr_with_project", new_callable=AsyncMock)
    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.set_merge_request_state", new_callable=AsyncMock)
    @patch("space.context.detect_git_context")
    def test_delete_decline_confirmation_deletes_nothing(self, mock_ctx, mock_state, mock_token, mock_resolve):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="proj", repo="test", branch="main")
        mock_resolve.side_effect = [(make_mr(number=42, title="Fix the widget"), "proj")]
        result = run_cli("mr", "delete", "42", env={"SPACE_TOKEN": "test"}, input="n\n")
        assert result.exit_code == 0
        mock_state.assert_not_called()
        # Reviewable audit list is printed before the prompt so the user can review what would be deleted.
        assert "#42" in result.output
        assert "Fix the widget" in result.output
        assert "proj" in result.output

    @patch("space.cli.mr_actions.resolve_mr_with_project", new_callable=AsyncMock)
    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.set_merge_request_state", new_callable=AsyncMock)
    @patch("space.context.detect_git_context")
    def test_delete_uses_resolved_project_not_state_project(self, mock_ctx, mock_state, mock_token, mock_resolve):
        # A URL ref resolves to a project different from SPACE_PROJECT; the delete must
        # target the resolved project, since review numbers are per-project.
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="ij", repo="ultimate", branch="main")
        mock_resolve.side_effect = [(make_mr(number=42), "OTHERPROJ")]
        result = run_cli(
            "mr",
            "delete",
            "https://jetbrains.team/p/OTHERPROJ/reviews/42/timeline",
            "--yes",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code == 0
        mock_state.assert_called_once_with("OTHERPROJ", ReviewRef(number=42), "Deleted")

    @patch("space.cli.mr_actions.resolve_mr_with_project", new_callable=AsyncMock)
    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.set_merge_request_state", new_callable=AsyncMock)
    @patch("space.context.detect_git_context")
    def test_delete_aborts_all_on_unresolvable_ref(self, mock_ctx, mock_state, mock_token, mock_resolve):
        # If any ref fails to resolve, nothing is deleted and the command exits non-zero.
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="ij", repo="ultimate", branch="main")
        mock_resolve.side_effect = [
            (make_mr(number=1), "ij"),
            click.ClickException("not found"),
        ]
        result = run_cli(
            "mr",
            "delete",
            "1",
            "999",
            "--yes",
            env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"},
        )
        assert result.exit_code != 0
        mock_state.assert_not_called()
        assert "999" in result.output

    @patch("space.cli.mr_actions.resolve_mr_with_project", new_callable=AsyncMock)
    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.set_merge_request_state", new_callable=AsyncMock)
    @patch("space.context.detect_git_context")
    def test_delete_reviewable_list_shows_titles(self, mock_ctx, mock_state, mock_token, mock_resolve):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="proj", repo="test", branch="main")
        mock_resolve.side_effect = [(make_mr(number=7, title="Fix the thing"), "proj")]
        result = run_cli("mr", "delete", "7", "--yes", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        assert "Fix the thing" in result.output


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
        mock_edit.assert_awaited_once_with("ij", ReviewRef(number=42), title="New title", description=None)
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
        mock_edit.assert_awaited_once_with("ij", ReviewRef(number=42), title=None, description="D")
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
        mock_edit.assert_awaited_once_with("ij", ReviewRef(number=42), title=None, description="")
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
        mock_edit.assert_awaited_once_with("ij", ReviewRef(number=42), title="T", description="D")
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
        mock_edit.assert_awaited_once_with("OTHERPROJ", ReviewRef(number=42), title="X", description=None)


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
        mock_state.assert_awaited_once_with("OTHERPROJ", ReviewRef(number=42), "Closed")


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
        mock_state.assert_awaited_once_with("OTHERPROJ", ReviewRef(number=42), "Opened")


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


# Review addressing ====================================================================================================

_ENV = {"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"}
_REVIEWS = re.compile(r"https://jetbrains\.team/api/http/projects/key:ij/code-reviews/[^/?]+(\?.*)?$")


def _path(request) -> str:
    return urlparse(str(request.url)).path


def _git_context():
    from space.context import GitContext
    return GitContext(project="ij", repo="ultimate", branch="main")


class TestReviewResolution:

    @patch("space.context.detect_git_context", side_effect=_git_context)
    def test_view_by_number_addresses_the_number(self, _ctx, httpx_mock, test_accounts):
        httpx_mock.add_response(url=_REVIEWS, json=copy.deepcopy(SAMPLE_MERGE_REQUEST))
        result = run_cli("mr", "view", "188120", env=_ENV)
        assert result.exit_code == 0
        assert [_path(r) for r in httpx_mock.get_requests()] == ["/api/http/projects/key:ij/code-reviews/number:188120"]

    @patch("space.context.detect_git_context", side_effect=_git_context)
    def test_delete_with_an_invalid_ref_deletes_nothing(self, _ctx, httpx_mock, test_accounts):
        httpx_mock.add_response(url=_REVIEWS, json=copy.deepcopy(SAMPLE_MERGE_REQUEST))
        result = run_cli("mr", "delete", "0", "188120", "--yes", env=_ENV)
        assert result.exit_code == 1
        assert "0: merge request numbers start at 1, got '0'" in result.output
        assert "nothing deleted" in result.output
        assert [(r.method, _path(r))
                for r in httpx_mock.get_requests()] == [("GET", "/api/http/projects/key:ij/code-reviews/number:188120")]


class TestNumberLessMr:

    @patch("space.cli.mr.resolve_mr_with_project", new_callable=AsyncMock)
    def test_timeline_addresses_the_id(self, mock_resolve, httpx_mock):
        mock_resolve.return_value = (make_mr(number=0, id="123456"), "ij")
        httpx_mock.add_response(url=_REVIEWS, json={})
        result = run_cli("mr", "timeline", env=_ENV)
        assert result.exit_code == 0
        assert _path(httpx_mock.get_request()) == "/api/http/projects/key:ij/code-reviews/id:123456"

    @pytest.mark.parametrize(("mr", "label"), [(make_mr(number=0, id="123456"), "id:123456"), (make_mr(), "188120")],
                             ids=["number-less", "numbered"])
    @patch("space.client.SpaceClient.list_merge_requests")
    @patch("space.context.detect_git_context", side_effect=_git_context)
    def test_list_labels_the_mr_so_it_parses_back(self, _ctx, mock_list, mr, label):
        mock_list.return_value = _async_gen_from([mr])
        result = run_cli("mr", "list", env=_ENV)
        assert result.exit_code == 0
        (row, ) = [line for line in result.output.splitlines() if mr.title in line]
        assert row.split()[0] == label


_NUMBER_LESS = {**SAMPLE_MERGE_REQUEST, "number": None}
del _NUMBER_LESS["number"]
_ID_PATH = "/api/http/projects/key:ij/code-reviews/id:123456"


def _review_url(suffix: str = "") -> re.Pattern:
    return re.compile(rf"https://jetbrains\.team/api/http/projects/key:ij/code-reviews/id:123456{suffix}(\?.*)?$")


class TestNumberLessMrActions:

    @pytest.mark.parametrize(("command", "state", "verb"), [("close", "Closed", "Closed"),
                                                            ("reopen", "Opened", "Reopened")])
    @patch("space.cli.mr_actions.resolve_mr_with_project", new_callable=AsyncMock)
    def test_state_change_addresses_the_id(self, mock_resolve, httpx_mock, command, state, verb):
        mock_resolve.return_value = (make_mr(number=0, id="123456"), "ij")
        httpx_mock.add_response(url=_review_url("/state"), method="PATCH", text="")
        result = run_cli("mr", command, env=_ENV)
        assert result.exit_code == 0
        request = httpx_mock.get_request()
        assert (_path(request), json.loads(request.content)) == (f"{_ID_PATH}/state", {"state": state})
        assert result.output.startswith(f"{verb} id:123456 ")

    @patch("space.cli.mr_actions.resolve_mr_with_project", new_callable=AsyncMock)
    def test_edit_addresses_the_id(self, mock_resolve, httpx_mock, test_accounts):
        mock_resolve.return_value = (make_mr(number=0, id="123456"), "ij")
        httpx_mock.add_response(url=_review_url("/title"), method="PATCH", text="")
        httpx_mock.add_response(url=_review_url(), method="GET", json=copy.deepcopy(_NUMBER_LESS))
        result = run_cli("mr", "edit", "-t", "T", env=_ENV)
        assert result.exit_code == 0
        assert [(r.method, _path(r)) for r in httpx_mock.get_requests()] == [("PATCH", f"{_ID_PATH}/title"),
                                                                             ("GET", _ID_PATH)]
        assert "Updated id:123456" in result.output

    @patch("space.cli.mr_actions.resolve_mr_with_project", new_callable=AsyncMock)
    def test_delete_addresses_the_id(self, mock_resolve, httpx_mock):
        mock_resolve.return_value = (make_mr(number=0, id="123456", title="Old thing"), "ij")
        httpx_mock.add_response(url=_review_url("/state"), method="PATCH", text="")
        result = run_cli("mr", "delete", "123456", "--yes", env=_ENV)
        assert result.exit_code == 0
        request = httpx_mock.get_request()
        assert (_path(request), json.loads(request.content)) == (f"{_ID_PATH}/state", {"state": "Deleted"})
        assert "  id:123456 Old thing  (ij)" in result.output

    @patch("space.context.detect_git_context", side_effect=_git_context)
    def test_close_by_explicit_id(self, _ctx, httpx_mock, test_accounts):
        httpx_mock.add_response(url=_review_url(), method="GET", json=copy.deepcopy(_NUMBER_LESS))
        httpx_mock.add_response(url=_review_url("/state"), method="PATCH", text="")
        result = run_cli("mr", "close", "id:123456", env=_ENV)
        assert result.exit_code == 0
        assert [(r.method, _path(r)) for r in httpx_mock.get_requests()] == [("GET", _ID_PATH),
                                                                             ("PATCH", f"{_ID_PATH}/state")]

    @patch("space.context.detect_git_context", side_effect=_git_context)
    def test_close_by_branch_resolves_then_addresses_the_id(self, _ctx, httpx_mock, test_accounts):
        listed = {k: v for k, v in _NUMBER_LESS.items() if k not in ("participants", "description", "feedChannel")}
        httpx_mock.add_response(
            url=re.compile(r"https://jetbrains\.team/api/http/projects/key:ij/code-reviews\?.*"),
            json={"data": [{"review": listed}]},
            is_reusable=True,
        )
        httpx_mock.add_response(url=_review_url(), method="GET", json=copy.deepcopy(_NUMBER_LESS))
        httpx_mock.add_response(url=_review_url("/state"), method="PATCH", text="")
        result = run_cli("mr", "close", "azhukova/fix-auth", env=_ENV)
        assert result.exit_code == 0
        assert [(r.method, _path(r)) for r in httpx_mock.get_requests()][-2:] == [("GET", _ID_PATH),
                                                                                  ("PATCH", f"{_ID_PATH}/state")]


class TestCommentAddressing:

    @patch("space.cli.mr_actions.resolve_mr_with_project", new_callable=AsyncMock)
    def test_comment_on_number_less_mr_addresses_the_id(self, mock_resolve, httpx_mock):
        mock_resolve.return_value = (make_mr(number=0, id="123456"), "ij")
        httpx_mock.add_response(url=_review_url(), method="GET", json={"feedChannel": {"id": "chan-1"}})
        httpx_mock.add_response(url=re.compile(r".*/send-message.*"), method="POST", json={"id": "msg-1"})
        result = run_cli("mr", "comment", "123456", "hi", env=_ENV)
        assert result.exit_code == 0
        lookup, post = httpx_mock.get_requests()
        assert _path(lookup) == _ID_PATH
        assert json.loads(post.content)["channel"] == "id:chan-1"
        assert "Comment posted on MR id:123456." in result.output

    @patch("space.cli.mr_actions.resolve_mr_with_project", new_callable=AsyncMock)
    def test_comment_on_numbered_mr_keeps_its_confirmation(self, mock_resolve, httpx_mock):
        mock_resolve.return_value = (make_mr(number=42), "ij")
        httpx_mock.add_response(
            url=re.compile(r".*/code-reviews/number:42(\?.*)?$"), method="GET", json={"feedChannel": {"id": "chan-1"}}
        )
        httpx_mock.add_response(url=re.compile(r".*/send-message.*"), method="POST", json={"id": "msg-1"})
        result = run_cli("mr", "comment", "42", "hi", env=_ENV)
        assert result.exit_code == 0
        assert "Comment posted on MR 42." in result.output

    @patch("space.cli.mr_actions.resolve_mr_with_project", new_callable=AsyncMock)
    def test_discuss_on_number_less_mr_addresses_the_id(self, mock_resolve, httpx_mock):
        mock_resolve.return_value = (make_mr(number=0, id="123456"), "ij")
        httpx_mock.add_response(
            url=re.compile(r".*/code-reviews/code-discussions.*"), method="POST", json={"channel": {"id": "disc-1"}}
        )
        result = run_cli(
            "mr", "discuss", "123456", "Look", "--file", "a.py", "--line", "3", "--revision", "abc", env=_ENV
        )
        assert result.exit_code == 0
        assert json.loads(httpx_mock.get_request().content)["reviewId"] == "id:123456"
