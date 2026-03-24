from __future__ import annotations

from datetime import datetime, timezone

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

import httpx

import space.clients as clients_module
import space.mcp.server as server_module
from space.context import AuthenticationError
from space.models import (
    AttemptDetails,
    BranchPair,
    CodeDiscussion,
    Comment,
    FailedBuild,
    FailedTest,
    MergeRequest,
    MRState,
    PatronusCheckConfig,
    PatronusCheckRun,
    PatronusCheckRunAttempt,
    PatronusRun,
    Problem,
    PushMode,
    Reviewer,
    ReviewRole,
    ReviewState,
    RunStatus,
    RunType,
    SpaceAccount,
    SpaceApp,
    TimelineEventClass,
    TimelineMessage,
)


def _account(name: str = "Anna Zhukova", username: str = "azhukova") -> SpaceAccount:
    first, last = (name.split(" ", 1) + [""])[:2]
    return SpaceAccount(id=f"id-{username}", username=username, email=f"{username}@test.com", first_name=first, last_name=last)


def _dt(hour: int = 10, minute: int = 0) -> datetime:
    return datetime(2026, 1, 16, hour, minute, tzinfo=timezone.utc)


def _mr(**overrides) -> MergeRequest:
    defaults = dict(
        id="123456", number=188120, title="Fix authentication bug",
        state=MRState.OPENED, created_at=_dt(),
        created_by=_account(), participants=(
            Reviewer(user=_account("John Doe", "jdoe"), role=ReviewRole.REVIEWER, state=ReviewState.PENDING),
        ),
        branch_pairs=(BranchPair("azhukova/fix-auth", "main", "ultimate"),),
    )
    defaults.update(overrides)
    return MergeRequest(**defaults)


def _run(**overrides) -> PatronusRun:
    defaults = dict(
        id="cc448634-880e-411f-9ee6-347e9a6087ac", name="Fix auth (dry run)",
        status=RunStatus.SUCCESSFUL, push_mode=PushMode.DRY_RUN,
        branch_pair=BranchPair("refs/patronus/safepush/abc", "master", "ultimate"),
        owner=_account(), started_at=_dt(hour=8), run_type=RunType.SAFE_PUSH,
        finished_at=_dt(hour=8, minute=8),
        space_review_url="https://jetbrains.team/p/IJ/reviews/188120/timeline",
    )
    defaults.update(overrides)
    return PatronusRun(**defaults)


def _check_config(name: str = "Compile All") -> PatronusCheckConfig:
    return PatronusCheckConfig(
        name=name, build_configuration_id=f"id_{name}", build_configuration_name=f"{name} Build",
        build_configuration_url=f"https://tc.example.com/{name}", project_name="Project", attempt_limit=3,
    )


def _check_run(name: str = "Compile All", status: RunStatus = RunStatus.SUCCESS, attempts=()) -> PatronusCheckRun:
    return PatronusCheckRun(
        id=f"check-{name}", config=_check_config(name), status=status,
        queued_at=_dt(hour=8), started_at=_dt(hour=8, minute=1), finished_at=_dt(hour=8, minute=5),
        skip_reason=None, attempts=attempts,
    )


class TestGetClient:

    def setup_method(self):
        clients_module._client = None

    def test_get_client_with_token(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        client = clients_module.get_client()
        assert client is not None
        assert client.token == "test-token"

    @patch("space.context._keyring_get", return_value=None)
    @patch("space.context.load_stored_token", return_value=None)
    def test_get_client_missing_token(self, mock_stored, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        with pytest.raises(AuthenticationError):
            clients_module.get_client()

    def test_get_client_singleton(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        assert clients_module.get_client() is clients_module.get_client()


class TestGetPatronusClient:

    def setup_method(self):
        clients_module._client = None
        clients_module._patronus_client = None

    def test_get_patronus_client_with_token(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        client = clients_module.get_patronus_client()
        assert client is not None
        assert client.token == "test-token"

    @patch("space.context._keyring_get", return_value=None)
    @patch("space.context.load_stored_token", return_value=None)
    def test_get_patronus_client_missing_token(self, mock_stored, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        with pytest.raises(AuthenticationError):
            clients_module.get_patronus_client()

    def test_get_patronus_client_singleton(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        assert clients_module.get_patronus_client() is clients_module.get_patronus_client()


class TestMCPErrorHandling:

    def setup_method(self):
        clients_module._client = None

    async def test_auth_error_message(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        mock_client = MagicMock()
        mock_client.get_merge_request = AsyncMock(side_effect=AuthenticationError("No token"))
        with patch.object(server_module, "get_client", return_value=mock_client):
            result = await server_module.get_merge_request("ij", "ultimate", "123")
        assert "Authentication required" in result

    async def test_http_error_message(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        mock_client = MagicMock()
        response = httpx.Response(404, request=httpx.Request("GET", "https://x"), text="Not found")
        mock_client.get_merge_request = AsyncMock(side_effect=httpx.HTTPStatusError("404", request=response.request, response=response))
        with patch.object(server_module, "get_client", return_value=mock_client):
            result = await server_module.get_merge_request("ij", "ultimate", "123")
        assert "Space API error (404)" in result

    async def test_generic_error_message(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        mock_client = MagicMock()
        mock_client.get_merge_request = AsyncMock(side_effect=RuntimeError("SilentError"))
        with patch.object(server_module, "get_client", return_value=mock_client):
            result = await server_module.get_merge_request("ij", "ultimate", "123")
        assert "**Error:**" in result
        assert "SilentError" in result


class TestMCPTools:

    def setup_method(self):
        clients_module._client = None

    async def test_get_merge_request_tool(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        mock_client = MagicMock()
        mock_client.get_merge_request = AsyncMock(return_value=_mr())
        with patch.object(server_module, "get_client", return_value=mock_client):
            result = await server_module.get_merge_request("ij", "ultimate", "123456")
        assert "# [MR 188120] Fix authentication bug" in result
        assert "**State:** Opened" in result

    async def test_get_merge_request_discussions_tool(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        mock_discussions = [
            CodeDiscussion(
                id="disc-1", file="/src/auth.py", line=42, resolved=False,
                comments=(
                    Comment(text="Please add tests", author=_account("John Doe", "jdoe"), created_at=_dt(), attachments=()),
                    Comment(text="Done", author=_account(), created_at=_dt(minute=5), attachments=()),
                ),
            ),
            TimelineMessage(
                event_class=TimelineEventClass.MC_MESSAGE, text="Someone started dry run",
                author=_account(), created_at=_dt(minute=10), attachments=(), thread_replies=(),
            ),
        ]
        mock_client = MagicMock()
        mock_client.get_merge_request_discussions = AsyncMock(return_value=mock_discussions)
        with patch.object(server_module, "get_client", return_value=mock_client):
            result = await server_module.get_merge_request_timeline("ij", "ultimate", "123456")
        assert "`/src/auth.py:42`" in result
        assert "Please add tests" in result
        assert "Someone started dry run" in result

    async def test_get_merge_requests_tool(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        mock_client = MagicMock()
        mock_client.list_merge_requests = AsyncMock(return_value=[_mr(), _mr(id="123457", title="Update deps", number=188121)])
        with patch.object(server_module, "get_client", return_value=mock_client):
            result = await server_module.get_merge_requests("ij", "ultimate")
        assert "| Title |" in result
        assert "Fix authentication bug" in result


class TestPatronusMCPTools:

    def setup_method(self):
        clients_module._patronus_client = None

    async def test_get_patronus_runs_tool(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        mock_space = MagicMock()
        mock_space.get_merge_request = AsyncMock(return_value=_mr(
            branch_pairs=(BranchPair("feature/test", "master", "ultimate"),),
        ))
        mock_patronus = MagicMock()
        mock_patronus.list_runs_for_review = AsyncMock(return_value=[_run()])
        mock_patronus.get_run_changes = AsyncMock(return_value=[])
        with patch.object(server_module, "get_client", return_value=mock_space), \
             patch.object(server_module, "get_patronus_client", return_value=mock_patronus):
            result = await server_module.get_patronus_runs("ij", "194108")
        assert "SUCCESSFUL" in result
        assert "cc448634" in result

    async def test_get_patronus_runs_tool_empty(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        mock_space = MagicMock()
        mock_space.get_merge_request = AsyncMock(return_value=_mr(
            branch_pairs=(BranchPair("feature/test", "master", "ultimate"),),
        ))
        mock_patronus = MagicMock()
        mock_patronus.list_runs_for_review = AsyncMock(return_value=[])
        with patch.object(server_module, "get_client", return_value=mock_space), \
             patch.object(server_module, "get_patronus_client", return_value=mock_patronus):
            result = await server_module.get_patronus_runs("ij", "194108")
        assert result == "No Patronus runs found."

    async def test_get_patronus_run_tool(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        failed_attempt = PatronusCheckRunAttempt(
            id="attempt-fail-1", number=0, status=RunStatus.FAILURE, build_id="98770",
        )
        checks = [
            _check_run("Compile All"),
            _check_run("Unit Tests", RunStatus.FAILURE, attempts=(failed_attempt,)),
        ]
        problems = (
            Problem(check=_check_config("Unit Tests"), title="3 tests failed in Unit Tests", details="Failures in `com.example.FooTest`"),
        )
        attempt_details = AttemptDetails(
            id="attempt-fail-1", number=0, status=RunStatus.FAILURE, build_id="98770",
            build_url="https://tc.example.com/build/98770",
            started_at=_dt(hour=8), finished_at=_dt(hour=8, minute=7),
            failed_tests=(FailedTest(name="com.example.FooTest.test something important"),),
            failed_builds=(FailedBuild(
                build_id="98770", build_url=None, build_configuration_id="test_Build",
                build_configuration_url=None, build_configuration_name="Unit Tests",
                full_project_name="Project / Tests", is_failed_to_start=False,
                problems=("Process exited with code 1",),
            ),),
        )

        mock_client = MagicMock()
        mock_client.get_run = AsyncMock(return_value=_run())
        mock_client.get_run_teamcity_checks = AsyncMock(return_value=checks)
        mock_client.get_run_problems = AsyncMock(return_value=problems)
        mock_client.get_attempt_details = AsyncMock(return_value=attempt_details)

        with patch.object(server_module, "get_patronus_client", return_value=mock_client):
            result = await server_module.get_patronus_run("cc448634-880e-411f-9ee6-347e9a6087ac")

        assert "# Fix auth (dry run)" in result
        assert "**Status:** SUCCESSFUL" in result
        assert "Compile All" in result
        assert "3 tests failed in Unit Tests" in result
        assert "## Failed Checks" in result
        assert "com.example.FooTest.test something important" in result

    async def test_start_patronus_dry_run_tool(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        mock_client = MagicMock()
        mock_client.start_safe_merge = AsyncMock(return_value={"jobId": "job-123"})
        with patch.object(server_module, "get_client", return_value=mock_client):
            result = await server_module.put_patronus_dry_run("ij", "194108")
        assert "Dry run started" in result

    async def test_start_patronus_dry_run_already_in_progress(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        error_response = [
            {"type": "Error", "message": "Cannot start safe merge: head already exists"},
        ]
        mock_client = MagicMock()
        mock_client.start_safe_merge = AsyncMock(return_value=error_response)
        with patch.object(server_module, "get_client", return_value=mock_client):
            result = await server_module.put_patronus_dry_run("ij", "194108")
        assert "already in progress" in result

    async def test_start_patronus_dry_run_exception_finds_run_in_timeline(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        mock_client = MagicMock()
        mock_client.start_safe_merge = AsyncMock(side_effect=RuntimeError("connection reset"))
        mock_client.get_merge_request_discussions = AsyncMock(return_value=[
            TimelineMessage(
                event_class=TimelineEventClass.MC_MESSAGE,
                text="Dry run started\nhttps://patronus.labs.jb.gg/robot/917ff740-e579-409a-b4a2-3014ba96529b",
                author=_account(), created_at=_dt(), attachments=(), thread_replies=(),
            ),
        ])
        mock_patronus = MagicMock()
        mock_patronus.get_run = AsyncMock(return_value=_run(id="917ff740-e579-409a-b4a2-3014ba96529b", status=RunStatus.RUNNING))
        with patch.object(server_module, "get_client", return_value=mock_client), \
             patch.object(server_module, "get_patronus_client", return_value=mock_patronus):
            result = await server_module.put_patronus_dry_run("ij", "194108")
        assert "connection reset" in result
        assert "is running" in result
        assert "917ff740-e579-409a-b4a2-3014ba96529b" in result

    async def test_start_patronus_dry_run_exception_no_run_fallback(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        mock_client = MagicMock()
        mock_client.start_safe_merge = AsyncMock(side_effect=RuntimeError("connection reset"))
        mock_client.get_merge_request_discussions = AsyncMock(return_value=[
            TimelineMessage(
                event_class=TimelineEventClass.MC_MESSAGE, text="Created the merge request",
                author=_account(), created_at=_dt(), attachments=(), thread_replies=(),
            ),
        ])
        with patch.object(server_module, "get_client", return_value=mock_client):
            result = await server_module.put_patronus_dry_run("ij", "194108")
        assert "connection reset" in result
        assert "may have started" in result

    async def test_post_cancel_patronus_run_tool(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        mock_client = MagicMock()
        mock_client.cancel_run = AsyncMock(return_value=None)
        with patch.object(server_module, "get_patronus_client", return_value=mock_client):
            result = await server_module.post_cancel_patronus_run("2d211ced-1976-4586-b4fe-dcf3ef285c34")
        assert "2d211ced-1976-4586-b4fe-dcf3ef285c34" in result
        assert "Cancellation" in result
