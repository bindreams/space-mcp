from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

import httpx

import space.mcp.server as server_module
from space.mcp.server import SpaceMCP
from space.transport import ApiTimeoutError
from space.models import (
    AttemptDetails,
    BranchPair,
    CodeDiscussion,
    Comment,
    FailedBuild,
    FailedTest,
    PatronusCheckRunAttempt,
    Problem,
    RunStatus,
    SpaceApp,
    TimelineEventClass,
    TimelineMessage,
)

from tests.factories import make_account, make_check_config, make_check_run, make_dt, make_mr, make_run


@pytest.fixture()
def mcp():
    server = SpaceMCP(token="test-token")
    server.space_client = MagicMock()
    server.patronus_client = MagicMock()
    return server


# Error handling =======================================================================================================


class TestMCPErrorHandling:

    async def test_auth_error_on_none_token(self):
        server = SpaceMCP(token=None)
        server.space_client.get_merge_request = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "401",
                request=httpx.Request("GET", "https://x"),
                response=httpx.Response(401, request=httpx.Request("GET", "https://x"), text="Unauthorized"),
            )
        )
        result = await server.get_merge_request("ij", "ultimate", "123")
        assert "Authentication required" in result

    async def test_http_error_message(self, mcp):
        response = httpx.Response(404, request=httpx.Request("GET", "https://x"), text="Not found")
        mcp.space_client.get_merge_request = AsyncMock(
            side_effect=httpx.HTTPStatusError("404", request=response.request, response=response)
        )
        result = await mcp.get_merge_request("ij", "ultimate", "123")
        assert "Space API error (404)" in result

    async def test_generic_error_message(self, mcp):
        mcp.space_client.get_merge_request = AsyncMock(side_effect=RuntimeError("SilentError"))
        result = await mcp.get_merge_request("ij", "ultimate", "123")
        assert "**Error:**" in result
        assert "SilentError" in result

    async def test_http_error_falls_back_to_reason_phrase(self, mcp):
        response = httpx.Response(500, request=httpx.Request("GET", "https://x"))
        mcp.space_client.get_merge_request = AsyncMock(
            side_effect=httpx.HTTPStatusError("500", request=response.request, response=response)
        )
        result = await mcp.get_merge_request("ij", "ultimate", "123")
        assert "Space API error (500)" in result

    async def test_space_timeout_surfaced_as_clear_error(self, mcp):

        async def boom(**kw):
            raise ApiTimeoutError("Space API did not respond after 30s")
            yield  # makes boom an async generator like list_merge_requests

        mcp.space_client.list_merge_requests = boom
        result = await mcp.get_merge_requests("ij", "ultimate", author="anna.zhukova")
        assert "Timed out" in result
        assert "Space API did not respond" in result

    async def test_patronus_timeout_not_mislabeled_as_space(self, mcp):
        """A Patronus timeout (same ApiTimeoutError type) must name Patronus, not Space."""
        mcp.patronus_client.get_run = AsyncMock(side_effect=ApiTimeoutError("Patronus did not respond after 30s"))
        result = await mcp.get_patronus_run("run-1")
        assert "Patronus did not respond" in result
        assert "Space" not in result


# MR tools =============================================================================================================


class TestMCPTools:

    async def test_get_merge_request_tool(self, mcp):
        mcp.space_client.get_merge_request = AsyncMock(return_value=make_mr())
        result = await mcp.get_merge_request("ij", "ultimate", "123456")
        assert "number: 188120" in result
        assert "title: Fix authentication bug" in result
        assert "state: Opened" in result

    async def test_get_merge_request_discussions_tool(self, mcp):
        mock_discussions = [
            CodeDiscussion(
                id="disc-1",
                file="/src/auth.py",
                line=42,
                resolved=False,
                comments=(
                    Comment(
                        text="Please add tests",
                        author=make_account("John Doe", "jdoe"),
                        created_at=make_dt(),
                        attachments=()
                    ),
                    Comment(text="Done", author=make_account(), created_at=make_dt(minute=5), attachments=()),
                ),
            ),
            TimelineMessage(
                event_class=TimelineEventClass.MC_MESSAGE,
                text="Someone started dry run",
                author=make_account(),
                created_at=make_dt(minute=10),
                attachments=(),
                thread_replies=(),
            ),
        ]
        mcp.space_client.get_merge_request_discussions = AsyncMock(return_value=mock_discussions)
        result = await mcp.get_merge_request_timeline("ij", "ultimate", "123456")
        assert "`/src/auth.py:42`" in result
        assert "Please add tests" in result
        assert "Someone started dry run" in result

    async def test_get_merge_requests_tool(self, mcp):

        async def mock_gen(*a, **kw):
            yield make_mr()

        mcp.space_client.list_merge_requests = mock_gen
        result = await mcp.get_merge_requests("ij", "ultimate")
        assert "merge-requests:" in result
        assert "Fix authentication bug" in result
        # Default limit=1, note should be appended
        assert "`limit` defaults to 1" in result

    async def test_get_merge_requests_passes_branch_to_client(self, mcp):
        """MCP tool passes branch through to client without adding text."""
        calls: list[dict] = []

        async def mock_gen(**kw):
            calls.append(kw)
            yield make_mr()

        mcp.space_client.list_merge_requests = mock_gen
        await mcp.get_merge_requests("ij", "ultimate", branch="feature/test")
        assert len(calls) == 1
        assert calls[0]["branch"] == "feature/test"
        assert calls[0]["state"] is None

    async def test_get_merge_requests_with_author(self, mcp):
        """MCP tool passes author to client."""
        calls: list[dict] = []

        async def mock_gen(**kw):
            calls.append(kw)
            yield make_mr()

        mcp.space_client.list_merge_requests = mock_gen
        await mcp.get_merge_requests("ij", "ultimate", author="azhukova")
        assert len(calls) == 1
        assert calls[0]["author"] == "azhukova"

    async def test_get_merge_requests_state_converted_to_enum(self, mcp):
        """MCP tool converts string state to MRStateFilter before passing to client."""
        from space.models import MRStateFilter
        calls: list[dict] = []

        async def mock_gen(**kw):
            calls.append(kw)
            yield make_mr()

        mcp.space_client.list_merge_requests = mock_gen
        await mcp.get_merge_requests("ij", "ultimate", state="Merged")
        assert len(calls) == 1
        assert calls[0]["state"] == MRStateFilter.MERGED

    async def test_get_merge_requests_explicit_limit_no_note(self, mcp):
        """Explicit limit does not append the default-limit note."""

        async def mock_gen(**kw):
            yield make_mr()

        mcp.space_client.list_merge_requests = mock_gen
        result = await mcp.get_merge_requests("ij", "ultimate", limit=10)
        assert "`limit` defaults to 1" not in result

    async def test_get_merge_requests_limit_zero_unlimited(self, mcp):
        """limit=0 consumes all results, no note."""

        async def mock_gen(**kw):
            yield make_mr()
            yield make_mr(id="123457", title="Second", number=2)

        mcp.space_client.list_merge_requests = mock_gen
        result = await mcp.get_merge_requests("ij", "ultimate", limit=0)
        assert "Fix authentication bug" in result
        assert "Second" in result
        assert "`limit` defaults to 1" not in result

    async def test_get_merge_requests_negative_limit(self, mcp):
        """Negative limit returns error."""
        result = await mcp.get_merge_requests("ij", "ultimate", limit=-1)
        assert "**Error:**" in result

    async def test_get_merge_requests_empty_with_default_limit(self, mcp):
        """Empty results with default limit still shows note."""

        async def mock_gen(**kw):
            return
            yield  # make it an async generator

        mcp.space_client.list_merge_requests = mock_gen
        result = await mcp.get_merge_requests("ij", "ultimate")
        assert "No merge requests found." in result
        assert "`limit` defaults to 1" in result


# Patronus tools =======================================================================================================


class TestPatronusMCPTools:

    async def test_get_patronus_runs_tool(self, mcp):
        mcp.space_client.get_merge_request = AsyncMock(
            return_value=make_mr(branch_pair=BranchPair("feature/test", "master", "ultimate"))
        )
        mcp.patronus_client.list_runs_for_review = AsyncMock(return_value=[make_run()])
        mcp.patronus_client.get_run_changes = AsyncMock(return_value=[])
        result = await mcp.get_patronus_runs("ij", "194108")
        assert "SUCCESSFUL" in result
        assert "cc448634-880e-411f-9ee6-347e9a6087ac" in result

    async def test_get_patronus_runs_tool_empty(self, mcp):
        mcp.space_client.get_merge_request = AsyncMock(
            return_value=make_mr(branch_pair=BranchPair("feature/test", "master", "ultimate"))
        )
        mcp.patronus_client.list_runs_for_review = AsyncMock(return_value=[])
        result = await mcp.get_patronus_runs("ij", "194108")
        assert result == "No Patronus runs found."

    async def test_get_patronus_run_tool(self, mcp):
        failed_attempt = PatronusCheckRunAttempt(
            id="attempt-fail-1",
            number=0,
            status=RunStatus.FAILURE,
            build_id="98770",
        )
        checks = [
            make_check_run("Compile All"),
            make_check_run("Unit Tests", RunStatus.FAILURE, attempts=(failed_attempt, )),
        ]
        problems = (
            Problem(
                check=make_check_config("Unit Tests"),
                title="3 tests failed in Unit Tests",
                details="Failures in `com.example.FooTest`"
            ),
        )
        attempt_details = AttemptDetails(
            id="attempt-fail-1",
            number=0,
            status=RunStatus.FAILURE,
            build_id="98770",
            build_url="https://tc.example.com/build/98770",
            started_at=make_dt(hour=8),
            finished_at=make_dt(hour=8, minute=7),
            failed_tests=(FailedTest(name="com.example.FooTest.test something important"), ),
            failed_builds=(
                FailedBuild(
                    build_id="98770",
                    build_url=None,
                    build_configuration_id="test_Build",
                    build_configuration_url=None,
                    build_configuration_name="Unit Tests",
                    full_project_name="Project / Tests",
                    is_failed_to_start=False,
                    problems=("Process exited with code 1", ),
                ),
            ),
        )

        mcp.patronus_client.get_run = AsyncMock(return_value=make_run())
        mcp.patronus_client.get_run_teamcity_checks = AsyncMock(return_value=checks)
        mcp.patronus_client.get_run_problems = AsyncMock(return_value=problems)
        mcp.patronus_client.get_attempt_details = AsyncMock(return_value=attempt_details)

        result = await mcp.get_patronus_run("cc448634-880e-411f-9ee6-347e9a6087ac")

        assert "name: Fix auth (dry run)" in result
        assert "status: SUCCESSFUL" in result
        assert "Compile All" in result
        assert "3 tests failed in Unit Tests" in result
        assert "test-failures:" in result
        assert "com.example.FooTest.test something important" in result

    async def test_start_patronus_dry_run_tool(self, mcp):
        mcp.space_client.start_safe_merge = AsyncMock(return_value={"jobId": "job-123"})
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert "Dry run started" in result

    async def test_start_patronus_dry_run_already_in_progress(self, mcp):
        error_response = [
            {"type": "Error", "message": "Cannot start safe merge: head already exists"},
        ]
        mcp.space_client.start_safe_merge = AsyncMock(return_value=error_response)
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert "already in progress" in result

    async def test_start_patronus_dry_run_exception_finds_run_in_timeline(self, mcp):
        mcp.space_client.start_safe_merge = AsyncMock(side_effect=httpx.ConnectError("connection reset"))
        mcp.space_client.get_merge_request_discussions = AsyncMock(
            return_value=[
                TimelineMessage(
                    event_class=TimelineEventClass.MC_MESSAGE,
                    text="Dry run started\nhttps://patronus.labs.jb.gg/robot/917ff740-e579-409a-b4a2-3014ba96529b",
                    author=make_account(),
                    created_at=make_dt(),
                    attachments=(),
                    thread_replies=(),
                ),
            ]
        )
        mcp.patronus_client.get_run = AsyncMock(
            return_value=make_run(id="917ff740-e579-409a-b4a2-3014ba96529b", status=RunStatus.RUNNING)
        )
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert "connection reset" in result
        assert "is running" in result
        assert "917ff740-e579-409a-b4a2-3014ba96529b" in result

    async def test_start_patronus_dry_run_exception_no_run_fallback(self, mcp):
        mcp.space_client.start_safe_merge = AsyncMock(side_effect=httpx.ConnectError("connection reset"))
        mcp.space_client.get_merge_request_discussions = AsyncMock(
            return_value=[
                TimelineMessage(
                    event_class=TimelineEventClass.MC_MESSAGE,
                    text="Created the merge request",
                    author=make_account(),
                    created_at=make_dt(),
                    attachments=(),
                    thread_replies=(),
                ),
            ]
        )
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert "connection reset" in result
        assert "may have started" in result

    async def test_post_cancel_patronus_run_tool(self, mcp):
        mcp.patronus_client.cancel_run = AsyncMock(return_value=None)
        result = await mcp.post_cancel_patronus_run("2d211ced-1976-4586-b4fe-dcf3ef285c34")
        assert "2d211ced-1976-4586-b4fe-dcf3ef285c34" in result
        assert "Cancellation" in result


# Comment / discussion MCP tools =======================================================================================


class TestCommentMCPTools:

    async def test_post_merge_request_comment(self, mcp):
        mcp.space_client.post_comment = AsyncMock(return_value="msg-1")
        result = await mcp.post_merge_request_comment("proj", "42", "hello")
        assert "42" in result
        mcp.space_client.post_comment.assert_called_once_with("proj", "42", "hello")

    async def test_post_code_discussion(self, mcp):
        mcp.space_client.create_code_discussion = AsyncMock(return_value="disc-chan-1")
        result = await mcp.post_code_discussion(
            "proj",
            "42",
            "repo",
            "abc123",
            "src/main.py",
            15,
            "Fix this",
        )
        assert "src/main.py:15" in result
        mcp.space_client.create_code_discussion.assert_called_once_with(
            "proj",
            "42",
            "repo",
            "abc123",
            "src/main.py",
            15,
            "Fix this",
        )

    async def test_post_reply_to_code_discussion(self, mcp):
        mcp.space_client.reply_to_discussion = AsyncMock(return_value=None)
        result = await mcp.post_reply_to_code_discussion(
            "proj",
            "42",
            "disc-chan-1",
            "my reply",
        )
        assert "Reply posted" in result
        mcp.space_client.reply_to_discussion.assert_called_once_with("disc-chan-1", "my reply")

    async def test_post_comment_error_handled(self, mcp):
        mcp.space_client.post_comment = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "403",
                request=MagicMock(),
                response=MagicMock(status_code=403, text="Forbidden", reason_phrase="Forbidden")
            ),
        )
        result = await mcp.post_merge_request_comment("proj", "42", "hello")
        assert "error" in result.lower() or "403" in result

    async def test_post_delete_merge_request(self, mcp):
        mcp.space_client.set_merge_request_state = AsyncMock(return_value=None)
        result = await mcp.post_delete_merge_request("proj", "42")
        assert "42" in result
        assert "deleted" in result.lower()
        mcp.space_client.set_merge_request_state.assert_called_once_with("proj", "42", "Deleted")
