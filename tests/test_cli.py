"""Tests for Space CLI commands."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from space.__main__ import main
from space.cli.app import parse_mr_ref
from space.models import (
    BranchPair,
    MergeRequest,
    MRState,
    Reviewer,
    ReviewRole,
    ReviewState,
    SpaceAccount,
)


def _account(name: str = "Anna Zhukova", username: str = "azhukova") -> SpaceAccount:
    first, last = (name.split(" ", 1) + [""])[:2]
    return SpaceAccount(id=f"id-{username}", username=username, email=f"{username}@test.com", first_name=first, last_name=last)


def _mr(**overrides) -> MergeRequest:
    defaults = dict(
        id="123456", number=188120, title="Fix authentication bug",
        state=MRState.OPENED, created_at=datetime(2026, 1, 15, 10, 30, tzinfo=timezone.utc),
        created_by=_account(), participants=(
            Reviewer(user=_account("John Doe", "jdoe"), role=ReviewRole.REVIEWER, state=ReviewState.ACCEPTED),
        ),
        branch_pairs=(BranchPair("azhukova/fix-auth", "main", "ultimate"),),
    )
    defaults.update(overrides)
    return MergeRequest(**defaults)


# MR reference parsing =====


class TestParseMrRef:
    def test_none(self):
        result = parse_mr_ref(None)
        assert result["number"] is None
        assert result["branch"] is None

    def test_numeric(self):
        result = parse_mr_ref("188120")
        assert result["number"] == "188120"
        assert result["branch"] is None

    def test_url(self):
        result = parse_mr_ref("https://jetbrains.team/p/ij/reviews/188120/timeline")
        assert result["number"] == "188120"
        assert result["project"] == "ij"

    def test_branch_name(self):
        result = parse_mr_ref("azhukova/fix-auth")
        assert result["branch"] == "azhukova/fix-auth"
        assert result["number"] is None


# CLI runner helpers =====


def _run(*args: str, env: dict | None = None) -> object:
    """Run a CLI command and return the result."""
    runner = CliRunner()
    return runner.invoke(main, list(args), env=env or {}, catch_exceptions=False)


# Top-level =====


class TestTopLevel:
    def test_help(self):
        result = _run("--help")
        assert result.exit_code == 0
        assert "space" in result.output.lower()
        assert "mr" in result.output
        assert "run" in result.output
        assert "auth" in result.output
        assert "api" in result.output
        assert "status" in result.output

    def test_version(self):
        result = _run("--version")
        assert result.exit_code == 0
        assert "1.0.0" in result.output

    def test_no_command_shows_help(self):
        result = _run()
        assert result.exit_code == 0
        assert "Commands:" in result.output


# mr view =====


class TestMrView:
    def test_help(self):
        result = _run("mr", "view", "--help")
        assert result.exit_code == 0
        assert "MR_REF" in result.output
        assert "--web" in result.output

    @patch("space.cli.mr.resolve_mr")
    def test_view_by_number(self, mock_resolve):
        mock_resolve.return_value = _mr()
        result = _run("mr", "view", "188120", env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"})
        assert result.exit_code == 0
        assert "#188120" in result.output
        assert "Fix authentication bug" in result.output
        assert "Opened" in result.output
        assert "John Doe" in result.output

    @patch("space.cli.mr.resolve_mr")
    def test_view_json(self, mock_resolve):
        mock_resolve.return_value = _mr(title="Fix auth", participants=(), branch_pairs=())
        result = _run("--json", "", "mr", "view", "188120",
                       env={"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"})
        assert result.exit_code == 0
        assert '"number": 188120' in result.output


# mr list =====


class TestMrList:
    def test_help(self):
        result = _run("mr", "list", "--help")
        assert result.exit_code == 0
        assert "--state" in result.output
        assert "--limit" in result.output

    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.list_merge_requests")
    @patch("space.context.detect_git_context")
    def test_list_empty(self, mock_ctx, mock_list, mock_token):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="ij", repo="ultimate", branch="main")
        mock_list.return_value = []
        result = _run("mr", "list", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        assert "No merge requests found" in result.output

    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.client.SpaceClient.list_merge_requests")
    @patch("space.context.detect_git_context")
    def test_list_with_results(self, mock_ctx, mock_list, mock_token):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="ij", repo="ultimate", branch="main")
        mock_list.return_value = [_mr(id="123", title="Fix bug", number=123)]
        result = _run("mr", "list", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        assert "Fix bug" in result.output
        assert "Opened" in result.output


# run list =====


class TestRunList:
    def test_help(self):
        result = _run("run", "list", "--help")
        assert result.exit_code == 0
        assert "--branch" in result.output
        assert "--base" in result.output

    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.patronus.PatronusClient.list_robots")
    @patch("space.client.SpaceClient.find_merge_request_by_branch", return_value=None)
    @patch("space.context.detect_git_context")
    def test_list_empty(self, mock_ctx, mock_find, mock_list, mock_token):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="ij", repo="ultimate", branch="main")
        mock_list.return_value = []
        result = _run("run", "list", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        assert "No Patronus runs found" in result.output


# run cancel =====


class TestRunCancel:
    @patch("space.cli.app.resolve_token", return_value="test-token")
    @patch("space.patronus.PatronusClient.cancel_robot")
    @patch("space.context.detect_git_context")
    def test_cancel(self, mock_ctx, mock_cancel, mock_token):
        from space.context import GitContext
        mock_ctx.return_value = GitContext(project="ij", repo="ultimate", branch="main")
        mock_cancel.return_value = None
        result = _run("run", "cancel", "cc448634-880e-411f-9ee6-347e9a6087ac", env={"SPACE_TOKEN": "test"})
        assert result.exit_code == 0
        assert "Cancelled" in result.output
        mock_cancel.assert_called_once_with("cc448634-880e-411f-9ee6-347e9a6087ac")
