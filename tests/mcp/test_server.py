from __future__ import annotations

import asyncio
import logging

import pytest
from unittest.mock import MagicMock, AsyncMock

import httpx

import space.mcp.server as server_module
from space.mcp.server import SpaceMCP
from space.transport import ApiTimeoutError
from space.client import AuthorNotFoundError
from space.mutation import Mutation, MutationCompletedError, MutationTarget
from space.models import (
    SafeMergeEvent,
    SafeMergeStart,
    AttemptDetails,
    AttemptStatus,
    BranchPair,
    CheckStatus,
    CodeDiscussion,
    Comment,
    FailedBuild,
    FailedTest,
    PatronusCheckRun,
    PatronusCheckRunAttempt,
    PatronusRun,
    Problem,
    ReviewRef,
    RunStatus,
    SpaceApp,
    TimelineEventClass,
    TimelineMessage,
)

from tests.sample_responses import wire_check, wire_run
from tests.factories import make_account, make_check_config, make_check_run, make_dt, load_yaml, make_mr, make_run


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

    async def test_unresolvable_author_surfaced_as_clear_error(self, mcp):
        """An unresolvable author (client raises ValueError) surfaces a clear, named error."""

        async def boom(**kw):
            raise AuthorNotFoundError("No Space user found for author 'no.such.user'.")
            yield  # makes boom an async generator like list_merge_requests

        mcp.space_client.list_merge_requests = boom
        result = await mcp.get_merge_requests("ij", "ultimate", author="no.such.user")
        assert "No Space user found" in result
        assert "no.such.user" in result


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

    @pytest.mark.parametrize(
        ("review_id", "ref"),
        [("194108", ReviewRef(number=194108)), ("AbCd", ReviewRef(id="AbCd")), ("²", ReviewRef(id="²"))],
        ids=["number", "id", "non-ascii-digit"],
    )
    async def test_get_merge_request_parses_the_review_id(self, mcp, review_id, ref):
        mcp.space_client.get_merge_request = AsyncMock(return_value=make_mr())
        await mcp.get_merge_request("ij", "ultimate", review_id)
        mcp.space_client.get_merge_request.assert_awaited_once_with("ij", "ultimate", ref)

    @pytest.mark.parametrize(
        ("review_id", "ref"),
        [("194108", ReviewRef(number=194108)), ("AbCd", ReviewRef(id="AbCd")), ("²", ReviewRef(id="²"))],
        ids=["number", "id", "non-ascii-digit"],
    )
    async def test_get_merge_request_timeline_parses_the_review_id(self, mcp, review_id, ref):
        mcp.space_client.get_merge_request_discussions = AsyncMock(return_value=[])
        await mcp.get_merge_request_timeline("ij", "ultimate", review_id)
        mcp.space_client.get_merge_request_discussions.assert_awaited_once_with("ij", "ultimate", ref)

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

    @pytest.fixture(autouse=True)
    def _resolvable_merge_request(self, mcp):
        """`put_patronus_dry_run` resolves a numeric review ID to the internal ID before starting."""
        mcp.space_client.get_merge_request = AsyncMock(return_value=make_mr(id="internal-mr-id"))

    async def test_get_patronus_runs_tool(self, mcp):
        mcp.space_client.get_merge_request = AsyncMock(
            return_value=make_mr(branch_pair=BranchPair("feature/test", "master", "ultimate"))
        )
        mcp.patronus_client.list_runs_for_review = AsyncMock(return_value=[make_run()])
        mcp.patronus_client.get_run_changes = AsyncMock(return_value=[])
        result = await mcp.get_patronus_runs("ij", "194108")
        assert "SUCCESS" in result
        assert "cc448634-880e-411f-9ee6-347e9a6087ac" in result

    async def test_get_patronus_runs_looks_up_the_parsed_ref(self, mcp):
        mcp.patronus_client.list_runs_for_review = AsyncMock(return_value=[])
        await mcp.get_patronus_runs("ij", "194108")
        mcp.space_client.get_merge_request.assert_awaited_once_with("ij", "", ReviewRef(number=194108))

    async def test_get_patronus_runs_looks_up_by_the_mr_number(self, mcp):
        mcp.space_client.get_merge_request = AsyncMock(return_value=make_mr(number=188120, id="AbCd"))
        mcp.patronus_client.list_runs_for_review = AsyncMock(return_value=[])
        await mcp.get_patronus_runs("ij", "AbCd")
        assert mcp.patronus_client.list_runs_for_review.await_args.args == ("ij", 188120)

    async def test_get_patronus_runs_uses_the_number_the_caller_gave(self, mcp):
        mcp.space_client.get_merge_request = AsyncMock(return_value=make_mr(number=0, id="123456"))
        mcp.patronus_client.list_runs_for_review = AsyncMock(return_value=[])
        await mcp.get_patronus_runs("ij", "194108")
        assert mcp.patronus_client.list_runs_for_review.await_args.args == ("ij", 194108)

    async def test_get_patronus_runs_for_a_number_less_mr(self, mcp):
        mcp.space_client.get_merge_request = AsyncMock(return_value=make_mr(number=0, id="123456"))
        mcp.patronus_client.list_runs_for_review = AsyncMock(return_value=[])
        result = await mcp.get_patronus_runs("ij", "id:123456")
        assert result == "Merge request id:123456 has no number, so its Patronus runs cannot be looked up."
        mcp.patronus_client.list_runs_for_review.assert_not_awaited()

    async def test_get_patronus_runs_logs_dropped_commit_fetch(self, mcp, caplog):
        run = make_run()
        mcp.space_client.get_merge_request = AsyncMock(
            return_value=make_mr(branch_pair=BranchPair("feature/test", "master", "ultimate"))
        )
        mcp.patronus_client.list_runs_for_review = AsyncMock(return_value=[run])
        mcp.patronus_client.get_run_changes = AsyncMock(side_effect=httpx.ConnectError("down"))
        with caplog.at_level(logging.DEBUG):
            result = await mcp.get_patronus_runs("ij", "194108")
        assert run.id in result
        assert [(r.levelno, r.getMessage()) for r in caplog.records if "commit" in r.getMessage()
                ] == [(logging.DEBUG, f"Dropped commit fetch for run {run.id}: ConnectError('down')")]

    async def test_get_patronus_runs_tool_propagates_a_cancelled_changes_fetch(self, mcp):
        # A cancellation is not a failed fetch: it propagates.
        mcp.space_client.get_merge_request = AsyncMock(
            return_value=make_mr(branch_pair=BranchPair("feature/test", "master", "ultimate"))
        )
        mcp.patronus_client.list_runs_for_review = AsyncMock(return_value=[make_run()])
        mcp.patronus_client.get_run_changes = AsyncMock(side_effect=asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await mcp.get_patronus_runs("ij", "194108")

    async def test_get_patronus_runs_tool_empty(self, mcp):
        mcp.space_client.get_merge_request = AsyncMock(
            return_value=make_mr(branch_pair=BranchPair("feature/test", "master", "ultimate"))
        )
        mcp.patronus_client.list_runs_for_review = AsyncMock(return_value=[])
        result = await mcp.get_patronus_runs("ij", "194108")
        assert result == "No Patronus runs found."

    async def test_get_patronus_runs_running_with_queued_check_shows_running(self, mcp, test_accounts):
        run = await PatronusRun.from_api(wire_run("RUNNING", finishDateTime=None), None)
        checks = [PatronusCheckRun.from_api(wire_check("QUEUED"))]
        mcp.space_client.get_merge_request = AsyncMock(
            return_value=make_mr(branch_pair=BranchPair("feature/test", "master", "ultimate"))
        )
        mcp.patronus_client.list_runs_for_review = AsyncMock(return_value=[run])
        mcp.patronus_client.get_run_changes = AsyncMock(return_value=[])
        mcp.patronus_client.get_run_teamcity_checks = AsyncMock(return_value=checks)

        result = await mcp.get_patronus_runs("ij", "194108")

        assert load_yaml(result)["patronus-runs"][0]["status"] == "RUNNING"

    async def test_get_patronus_run_running_with_queued_check_shows_running(self, mcp, test_accounts):
        run = await PatronusRun.from_api(wire_run("RUNNING", finishDateTime=None), None)
        checks = [
            PatronusCheckRun.from_api(wire_check("QUEUED")),
            PatronusCheckRun.from_api(wire_check("CANCELED", "B"))
        ]
        mcp.patronus_client.get_run = AsyncMock(return_value=run)
        mcp.patronus_client.get_run_teamcity_checks = AsyncMock(return_value=checks)
        mcp.patronus_client.get_run_problems = AsyncMock(return_value=())

        result = await mcp.get_patronus_run(run.id)

        parsed = load_yaml(result)["patronus-run"]
        assert parsed["status"] == "RUNNING"
        assert [c["status"] for c in parsed["teamcity-checks"]["checks"]] == ["QUEUED", "CANCELED"]

    async def test_get_patronus_run_tool(self, mcp):
        failed_attempt = PatronusCheckRunAttempt(
            id="attempt-fail-1",
            number=0,
            status=AttemptStatus.FAILURE,
            build_id="98770",
        )
        checks = [
            make_check_run("Compile All"),
            make_check_run("Unit Tests", CheckStatus.FAILURE, attempts=(failed_attempt, )),
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
            status=AttemptStatus.FAILURE,
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
        assert load_yaml(result)["patronus-run"]["status"] == "SUCCESS"
        assert "Compile All" in result
        assert "3 tests failed in Unit Tests" in result
        assert "test-failures:" in result
        assert "com.example.FooTest.test something important" in result

    async def test_start_patronus_dry_run_tool(self, mcp):
        mcp.space_client.start_safe_merge = AsyncMock(return_value=SafeMergeStart(job_id="job-123"))
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert "Dry run started" in result

    async def test_start_patronus_dry_run_already_in_progress(self, mcp):
        error_response = SafeMergeStart(
            events=(SafeMergeEvent("Error", "Cannot start safe merge: head already exists"), )
        )
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

    @staticmethod
    def _timeline_with_run(mcp, status):
        run_id = "917ff740-e579-409a-b4a2-3014ba96529b"
        mcp.space_client.start_safe_merge = AsyncMock(side_effect=httpx.ConnectError("connection reset"))
        mcp.space_client.get_merge_request_discussions = AsyncMock(
            return_value=[
                TimelineMessage(
                    event_class=TimelineEventClass.MC_MESSAGE,
                    text=f"Dry run started\nhttps://patronus.labs.jb.gg/robot/{run_id}",
                    author=make_account(),
                    created_at=make_dt(),
                    attachments=(),
                    thread_replies=(),
                ),
            ]
        )
        mcp.patronus_client.get_run = AsyncMock(return_value=make_run(id=run_id, status=status))

    async def test_dry_run_followup_for_settled_run_gives_unconfirmed_note(self, mcp, caplog):
        self._timeline_with_run(mcp, RunStatus.CANCELED)
        with caplog.at_level(logging.DEBUG):
            result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result == f"{self._ORIGINAL}\n\n{self._UNCONFIRMED}"
        (record, ) = [r for r in caplog.records if "is settled" in r.getMessage()]
        assert record.levelno == logging.DEBUG
        assert record.getMessage() == (
            "Dry run follow-up for review #194108: last run 917ff740-e579-409a-b4a2-3014ba96529b is settled (CANCELED)"
        )

    @pytest.mark.unrecognised_api_value
    async def test_dry_run_followup_for_unknown_run_reports_it(self, mcp):
        self._timeline_with_run(mcp, RunStatus("NO_SUCH_STATUS"))
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert "a dry run exists for this merge request" in result
        assert "917ff740-e579-409a-b4a2-3014ba96529b" in result
        assert "status: UNKNOWN" in result
        assert "may have started" not in result

    @pytest.mark.parametrize("exc_type", [asyncio.CancelledError, KeyboardInterrupt, SystemExit])
    @pytest.mark.parametrize("failure_point", ["discussions", "get_run"])
    async def test_dry_run_followup_does_not_swallow_base_exception(self, mcp, exc_type, failure_point):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        if failure_point == "discussions":
            mcp.space_client.get_merge_request_discussions = AsyncMock(side_effect=exc_type())
        else:
            mcp.patronus_client.get_run = AsyncMock(side_effect=exc_type())
        with pytest.raises(exc_type):
            await mcp.put_patronus_dry_run("ij", "194108")

    # Follow-up failures -----------------------------------------------------------------------------------------------

    _RID = "917ff740-e579-409a-b4a2-3014ba96529b"
    _ORIGINAL = "**Error:** connection reset"
    _HINT = (
        "Use `get_patronus_runs` with the project and review ID to check the status of existing runs. "
        "Use `post_cancel_patronus_run` to cancel a stuck run before retrying."
    )
    _UNCONFIRMED = "Note: the dry run may have started despite this error. " + _HINT

    @staticmethod
    def _status_error(status: int, text: str = "failure") -> httpx.HTTPStatusError:
        request = httpx.Request("GET", "https://x")
        return httpx.HTTPStatusError(text, request=request, response=httpx.Response(status, request=request))

    @staticmethod
    def _checking_failed(error: str) -> str:
        return (
            f"Note: the dry run may have started despite this error, but checking failed: {error}. " +
            TestPatronusMCPTools._HINT
        )

    @staticmethod
    def _timeline_without_run(mcp):
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

    async def test_dry_run_followup_unexpected_error_keeps_original_error(self, mcp):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.space_client.get_merge_request_discussions = AsyncMock(side_effect=ValueError("owner missing 'id'"))
        result = await mcp.put_patronus_dry_run("ij", "194108")
        expected = self._checking_failed("owner missing 'id'")
        assert result == f"{self._ORIGINAL}\n\n{expected}"

    async def test_dry_run_followup_error_without_message_names_type(self, mcp):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.space_client.get_merge_request_discussions = AsyncMock(side_effect=ValueError())
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result == f"{self._ORIGINAL}\n\n{self._checking_failed('ValueError')}"

    async def test_dry_run_followup_keyerror_before_run_id_shows_text(self, mcp):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.space_client.get_merge_request_discussions = AsyncMock(side_effect=KeyError("id"))
        result = await mcp.put_patronus_dry_run("ij", "194108")
        expected = self._checking_failed("'id'")
        assert result == f"{self._ORIGINAL}\n\n{expected}"

    async def test_dry_run_followup_http_status_error_before_run_id_shows_status(self, mcp):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.space_client.get_merge_request_discussions = AsyncMock(side_effect=self._status_error(403))
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result == f"{self._ORIGINAL}\n\n{self._checking_failed('HTTP 403')}"

    @pytest.mark.parametrize(
        "exc", [httpx.ConnectError("x"), httpx.TimeoutException("x"),
                httpx.ReadError("x")],
        ids=["connect", "timeout", "read"]
    )
    async def test_dry_run_followup_transport_error_gives_unconfirmed_note(self, mcp, exc):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.space_client.get_merge_request_discussions = AsyncMock(side_effect=exc)
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result == f"{self._ORIGINAL}\n\n{self._UNCONFIRMED}"

    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            (ValueError("bad status payload"), "bad status payload"),
            (KeyError("status"), "'status'"),
            (_status_error.__func__(500), "HTTP 500"),
            (httpx.ConnectError("patronus down"), "patronus down"),
            (httpx.TimeoutException("slow"), "slow"),
            (httpx.ReadError("reset"), "reset"),
        ],
        ids=["value", "key", "status", "connect", "timeout", "read"],
    )
    async def test_dry_run_followup_keeps_run_id_on_read_failure(self, mcp, exc, expected):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.patronus_client.get_run = AsyncMock(side_effect=exc)
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result == (
            f"{self._ORIGINAL}\n\n"
            f"However, a dry run may exist for this merge request (run `{self._RID}`), "
            f"but its status could not be read: {expected}. "
            f"Use `get_patronus_run` with run ID `{self._RID}` to inspect it before starting another."
        )

    @pytest.mark.parametrize("failure_point", ["discussions", "get_run"])
    async def test_dry_run_followup_describe_is_guarded(self, mcp, failure_point):

        class UnprintableError(Exception):

            def __str__(self) -> str:
                raise RuntimeError("no text")

        self._timeline_with_run(mcp, RunStatus.RUNNING)
        if failure_point == "discussions":
            mcp.space_client.get_merge_request_discussions = AsyncMock(side_effect=UnprintableError())
            expected = self._checking_failed("UnprintableError")
        else:
            mcp.patronus_client.get_run = AsyncMock(side_effect=UnprintableError())
            expected = (
                f"However, a dry run may exist for this merge request (run `{self._RID}`), "
                f"but its status could not be read: UnprintableError. "
                f"Use `get_patronus_run` with run ID `{self._RID}` to inspect it before starting another."
            )
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result == f"{self._ORIGINAL}\n\n{expected}"

    async def test_dry_run_followup_error_text_is_one_line_without_trailing_period(self, mcp):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.space_client.get_merge_request_discussions = AsyncMock(side_effect=ValueError("line one\nline two."))
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result == f"{self._ORIGINAL}\n\n{self._checking_failed('line one line two')}"

    @pytest.mark.parametrize("ending", ["?", "!"])
    async def test_dry_run_followup_error_ending_in_punctuation_gets_no_period(self, mcp, ending):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.space_client.get_merge_request_discussions = AsyncMock(side_effect=ValueError(f"down{ending}"))
        result = await mcp.put_patronus_dry_run("ij", "194108")
        expected = f"{self._ORIGINAL}\n\nNote: the dry run may have started despite this error, but checking failed: "
        assert result == f"{expected}down{ending} {self._HINT}"

    async def test_dry_run_followup_reraises_assertion_error(self, mcp):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.space_client.get_merge_request_discussions = AsyncMock(side_effect=AssertionError("contract"))
        with pytest.raises(AssertionError, match="contract"):
            await server_module._check_dry_run_started(
                mcp.space_client, mcp.patronus_client, "ij", ReviewRef(number=194108), strict_hint=""
            )

    @pytest.mark.parametrize("start", [SafeMergeStart(events=()), SafeMergeStart()], ids=["empty-list", "empty-dict"])
    async def test_dry_run_empty_responses_render_as_today(self, start):
        assert server_module._format_safe_merge_result(start) == "Dry run started."

    async def test_dry_run_unreadable_accepted_response_gets_the_followup(self, mcp):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        err = MutationCompletedError(
            Mutation.SAFE_MERGE_ACCEPTED,
            MutationTarget("ij", ReviewRef(number=194108)),
            ValueError("unexpected safe-merge response: int"),
        )
        mcp.space_client.start_safe_merge = AsyncMock(side_effect=err)
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result.startswith(
            "**Error:** Space accepted the safe-merge request for merge request #194108, but reading the response "
            "failed: unexpected safe-merge response: int\n\nHowever, a dry run **is running**"
        )
        assert f"(run `{self._RID}`" in result

    async def test_dry_run_starts_with_the_resolved_internal_id(self, mcp):
        mcp.space_client.start_safe_merge = AsyncMock(return_value=SafeMergeStart(job_id="job-123"))
        await mcp.put_patronus_dry_run("ij", "194108")
        mcp.space_client.get_merge_request.assert_awaited_once_with("ij", "", ReviewRef(number=194108))
        mcp.space_client.start_safe_merge.assert_awaited_once_with(
            "ij", mcp.space_client.get_merge_request.return_value, operation="DryRun"
        )

    async def test_dry_run_with_non_ascii_digits_skips_the_lookup(self, mcp):
        mcp.space_client.start_safe_merge = AsyncMock(return_value=SafeMergeStart(job_id="job-123"))
        await mcp.put_patronus_dry_run("ij", "²")
        mcp.space_client.get_merge_request.assert_not_awaited()
        mcp.space_client.start_safe_merge.assert_awaited_once_with("ij", ReviewRef(id="²"), operation="DryRun")

    async def test_dry_run_followup_reads_the_original_ref(self, mcp):
        self._timeline_without_run(mcp)
        mcp.space_client.start_safe_merge = AsyncMock(side_effect=httpx.ConnectError("connection reset"))
        await mcp.put_patronus_dry_run("ij", "194108")
        mcp.space_client.get_merge_request_discussions.assert_awaited_once_with("ij", "", ReviewRef(number=194108))

    async def test_dry_run_with_empty_review_id_is_an_error(self, mcp):
        mcp.space_client.start_safe_merge = AsyncMock()
        mcp.space_client.get_merge_request_discussions = AsyncMock()
        result = await mcp.put_patronus_dry_run("ij", "")
        assert result == "**Error:** empty merge request reference"
        mcp.space_client.get_merge_request.assert_not_awaited()
        mcp.space_client.start_safe_merge.assert_not_awaited()
        mcp.space_client.get_merge_request_discussions.assert_not_awaited()

    async def test_dry_run_with_internal_id_skips_the_lookup(self, mcp):
        mcp.space_client.start_safe_merge = AsyncMock(return_value=SafeMergeStart(job_id="job-123"))
        await mcp.put_patronus_dry_run("ij", "AbCd-internal")
        mcp.space_client.get_merge_request.assert_not_awaited()
        mcp.space_client.start_safe_merge.assert_awaited_once_with(
            "ij", ReviewRef(id="AbCd-internal"), operation="DryRun"
        )

    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            (_status_error.__func__(404, "x"), "**Space API error (404):** Not Found"),
            (httpx.ConnectError("connection reset"), "**Error:** connection reset"),
        ],
        ids=["not-found", "connect"],
    )
    async def test_dry_run_lookup_failure_gets_no_followup(self, mcp, exc, expected):
        mcp.space_client.get_merge_request = AsyncMock(side_effect=exc)
        mcp.space_client.start_safe_merge = AsyncMock()
        mcp.space_client.get_merge_request_discussions = AsyncMock()
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result == expected
        mcp.space_client.start_safe_merge.assert_not_awaited()
        mcp.space_client.get_merge_request_discussions.assert_not_awaited()

    @pytest.mark.parametrize(
        ("exc", "error"),
        [
            (httpx.DecodingError("bad gzip"), "bad gzip"),
            (httpx.TooManyRedirects("loop"), "loop"),
            (RuntimeError("odd"), "odd"),
            (
                UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
                "'utf-8' codec can't decode byte 0xff in position 0: invalid start byte",
            ),
        ],
        ids=["decoding", "redirects", "runtime", "unicode"],
    )
    async def test_dry_run_followup_runs_for_any_failure_of_the_start_call(self, mcp, exc, error):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.space_client.start_safe_merge = AsyncMock(side_effect=exc)
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result.startswith(f"**Error:** {error}\n\n")
        assert "(run `917ff740-e579-409a-b4a2-3014ba96529b`" in result
        assert "is running" in result

    @pytest.mark.parametrize("stage", ["start", "format"])
    async def test_dry_run_original_failure_is_logged_with_traceback(self, mcp, caplog, stage):
        self._timeline_without_run(mcp)
        if stage == "start":
            exc = RuntimeError("odd")
        else:
            exc = MutationCompletedError(
                Mutation.SAFE_MERGE_ACCEPTED,
                MutationTarget("ij", ReviewRef(number=194108)),
                ValueError("unexpected safe-merge response: int"),
            )
        mcp.space_client.start_safe_merge = AsyncMock(side_effect=exc)
        with caplog.at_level(logging.DEBUG):
            await mcp.put_patronus_dry_run("ij", "194108")
        (record, ) = [r for r in caplog.records if "Space accepted" in r.getMessage() or "odd" in r.getMessage()]
        assert record.levelno == logging.DEBUG
        assert "194108" in record.getMessage()
        assert record.exc_info is not None and record.exc_info[1] is exc

    async def test_dry_run_original_error_that_cannot_be_rendered_keeps_the_followup(self, mcp):

        class UnprintableError(Exception):

            def __str__(self) -> str:
                raise RuntimeError("no text")

        self._timeline_without_run(mcp)
        mcp.space_client.start_safe_merge = AsyncMock(side_effect=UnprintableError())
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result == f"**Error:** UnprintableError\n\n{self._UNCONFIRMED}"

    async def test_dry_run_followup_assertion_error_after_run_id_names_the_run(self, mcp, caplog):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.patronus_client.get_run = AsyncMock(side_effect=AssertionError("contract"))
        with caplog.at_level(logging.DEBUG), pytest.raises(AssertionError, match="contract") as caught:
            await server_module._check_dry_run_started(
                mcp.space_client, mcp.patronus_client, "ij", ReviewRef(number=194108), strict_hint=""
            )
        assert caught.value.__notes__ == [
            "dry-run follow-up: run 917ff740-e579-409a-b4a2-3014ba96529b exists for this merge request"
        ]
        (record, ) = [r for r in caplog.records if "917ff740-e579-409a-b4a2-3014ba96529b" in r.getMessage()]
        assert record.levelno == logging.DEBUG
        assert record.exc_info is not None and record.exc_info[1] is caught.value

    async def test_dry_run_followup_assertion_error_before_run_id_has_no_note(self, mcp):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.space_client.get_merge_request_discussions = AsyncMock(side_effect=AssertionError("contract"))
        with pytest.raises(AssertionError, match="contract") as caught:
            await server_module._check_dry_run_started(
                mcp.space_client, mcp.patronus_client, "ij", ReviewRef(number=194108), strict_hint=""
            )
        assert not hasattr(caught.value, "__notes__")

    @pytest.mark.parametrize("site", ["start", "format", "followup"])
    async def test_dry_run_assertion_error_is_not_turned_into_a_followup(self, mcp, monkeypatch, site):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.space_client.get_merge_request_discussions = AsyncMock(
            side_effect=AssertionError("contract") if site == "followup" else None
        )
        if site == "start":
            mcp.space_client.start_safe_merge = AsyncMock(side_effect=AssertionError("contract"))
        elif site == "format":
            mcp.space_client.start_safe_merge = AsyncMock(return_value=SafeMergeStart())
            monkeypatch.setattr(
                server_module, "_format_safe_merge_result", MagicMock(side_effect=AssertionError("contract"))
            )
        result = await mcp.put_patronus_dry_run("ij", "194108")
        # the tool wrapper renders the escaped exception, so the original error is replaced by it
        assert result == "**Error:** contract"
        if site == "followup":
            mcp.space_client.get_merge_request_discussions.assert_awaited_once()
        else:
            mcp.space_client.get_merge_request_discussions.assert_not_awaited()

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            pytest.param(
                RunStatus.RUNNING,
                "However, a dry run **is running** for this merge request "
                "(run `917ff740-e579-409a-b4a2-3014ba96529b`, status: RUNNING). "
                "Use `get_patronus_run` with run ID `917ff740-e579-409a-b4a2-3014ba96529b` to track progress.",
                id="running",
            ),
            pytest.param(
                RunStatus.CANCELING,
                "However, a dry run **is being cancelled** for this merge request "
                "(run `917ff740-e579-409a-b4a2-3014ba96529b`, status: CANCELING). "
                "Use `get_patronus_run` with run ID `917ff740-e579-409a-b4a2-3014ba96529b` to track progress.",
                id="canceling",
            ),
            pytest.param(
                "NO_SUCH_STATUS",
                "However, a dry run exists for this merge request "
                "(run `917ff740-e579-409a-b4a2-3014ba96529b`, status: UNKNOWN). "
                "Use `get_patronus_run` with run ID `917ff740-e579-409a-b4a2-3014ba96529b` "
                "to inspect it before starting another.",
                marks=pytest.mark.unrecognised_api_value,
                id="unknown",
            ),
        ],
    )
    async def test_dry_run_followup_note_for_an_existing_run(self, mcp, status, expected):
        if isinstance(status, str):  # a value Patronus does not send; parsed here so collection stays clean
            status = RunStatus(status)
        self._timeline_with_run(mcp, status)
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result == f"{self._ORIGINAL}\n\n{expected}"

    @pytest.mark.parametrize("exc_type", [asyncio.CancelledError, KeyboardInterrupt, SystemExit])
    @pytest.mark.parametrize("site", ["start", "format"])
    async def test_dry_run_start_path_does_not_swallow_base_exception(self, mcp, monkeypatch, exc_type, site):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        if site == "start":
            mcp.space_client.start_safe_merge = AsyncMock(side_effect=exc_type())
        else:
            mcp.space_client.start_safe_merge = AsyncMock(return_value=SafeMergeStart())
            monkeypatch.setattr(server_module, "_format_safe_merge_result", MagicMock(side_effect=exc_type()))
        with pytest.raises(exc_type):
            await mcp.put_patronus_dry_run("ij", "194108")

    async def test_dry_run_followup_describe_survives_a_failing_response_access(self, mcp):

        class BrokenResponseError(httpx.HTTPStatusError):

            @property
            def response(self):
                raise RuntimeError("no response")

            @response.setter
            def response(self, value):
                pass

        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.space_client.get_merge_request_discussions = AsyncMock(
            side_effect=BrokenResponseError("x", request=httpx.Request("GET", "https://x"), response=None)
        )
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result == f"{self._ORIGINAL}\n\n{self._checking_failed('BrokenResponseError')}"

    async def test_dry_run_followup_whitespace_only_message_names_the_type(self, mcp):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.space_client.get_merge_request_discussions = AsyncMock(side_effect=ValueError("  \n "))
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result == f"{self._ORIGINAL}\n\n{self._checking_failed('ValueError')}"

    @pytest.mark.parametrize(
        ("status", "expected"),
        [(401, "**Space API error (401):** Unauthorized"), (500, "**Space API error (500):** Internal Server Error")],
    )
    async def test_dry_run_start_http_error_is_rendered_with_the_followup(self, mcp, status, expected):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.space_client.start_safe_merge = AsyncMock(side_effect=self._status_error(status))
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result == (
            f"{expected}\n\n"
            "However, a dry run **is running** for this merge request "
            "(run `917ff740-e579-409a-b4a2-3014ba96529b`, status: RUNNING). "
            "Use `get_patronus_run` with run ID `917ff740-e579-409a-b4a2-3014ba96529b` to track progress."
        )

    async def test_dry_run_followup_runs_after_lost_connection(self, mcp):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        mcp.space_client.start_safe_merge = AsyncMock(side_effect=httpx.ReadError("connection lost"))
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result.startswith("**Error:** connection lost\n\n")
        assert self._RID in result
        assert "is running" in result

    @pytest.mark.parametrize("failure_point", ["discussions", "get_run"])
    @pytest.mark.parametrize(
        ("exc", "traceback"),
        [
            (ValueError("boom"), True),
            (_status_error.__func__(500, "boom"), True),
            (httpx.ConnectError("boom"), False),
            (httpx.TimeoutException("boom"), False),
            (httpx.ReadError("boom"), False),
        ],
        ids=["value", "status", "connect", "timeout", "read"],
    )
    async def test_dry_run_followup_failure_log_record(self, mcp, caplog, failure_point, exc, traceback):
        self._timeline_with_run(mcp, RunStatus.RUNNING)
        if failure_point == "discussions":
            mcp.space_client.get_merge_request_discussions = AsyncMock(side_effect=exc)
        else:
            mcp.patronus_client.get_run = AsyncMock(side_effect=exc)
        with caplog.at_level(logging.DEBUG):
            await mcp.put_patronus_dry_run("ij", "194108")
        (record, ) = [r for r in caplog.records if "boom" in r.getMessage()]
        assert record.levelno == logging.DEBUG
        assert "194108" in record.getMessage()
        if failure_point == "get_run":
            assert self._RID in record.getMessage()
        if traceback:
            assert record.exc_info is not None and record.exc_info[1] is exc
        else:
            assert not record.exc_info
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    async def test_dry_run_followup_no_run_id_is_logged(self, mcp, caplog):
        self._timeline_without_run(mcp)
        with caplog.at_level(logging.DEBUG):
            result = await mcp.put_patronus_dry_run("ij", "194108")
        assert result == f"{self._ORIGINAL}\n\n{self._UNCONFIRMED}"
        (record, ) = [r for r in caplog.records if "no run ID in the timeline" in r.getMessage()]
        assert record.levelno == logging.DEBUG
        assert "194108" in record.getMessage()

    async def test_dry_run_followup_for_canceling_run_says_being_cancelled(self, mcp):
        self._timeline_with_run(mcp, RunStatus.CANCELING)
        result = await mcp.put_patronus_dry_run("ij", "194108")
        assert "is being cancelled" in result
        assert "is running" not in result

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
        mcp.space_client.post_comment.assert_called_once_with("proj", ReviewRef(number=42), "hello")

    @pytest.mark.parametrize(("review_id", "ref"), [("42", ReviewRef(number=42)), ("²", ReviewRef(id="²"))],
                             ids=["number", "non-ascii-digit"])
    async def test_comment_and_discussion_parse_the_review_id(self, mcp, review_id, ref):
        mcp.space_client.post_comment = AsyncMock(return_value="msg-1")
        mcp.space_client.create_code_discussion = AsyncMock(return_value="disc-1")
        await mcp.post_merge_request_comment("proj", review_id, "hello")
        await mcp.post_code_discussion("proj", review_id, "repo", "abc", "f.py", 1, "t")
        assert mcp.space_client.post_comment.await_args.args[1] == ref
        assert mcp.space_client.create_code_discussion.await_args.args[1] == ref

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
            ReviewRef(number=42),
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

    async def test_reply_ignores_an_empty_review_id(self, mcp):
        mcp.space_client.reply_to_discussion = AsyncMock(return_value=None)
        result = await mcp.post_reply_to_code_discussion("ij", "", "chan", "t")
        assert result == "Reply posted."
        mcp.space_client.reply_to_discussion.assert_awaited_once_with("chan", "t")

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
        mcp.space_client.set_merge_request_state.assert_called_once_with("proj", ReviewRef(number=42), "Deleted")

    @pytest.mark.parametrize(
        "tool", ["post_close_merge_request", "post_reopen_merge_request", "post_delete_merge_request"]
    )
    @pytest.mark.parametrize(
        ("review_id", "ref"),
        [("42", ReviewRef(number=42)), ("²", ReviewRef(id="²"))],
        ids=["number", "non-ascii-digit"],
    )
    async def test_state_tools_parse_the_review_id(self, mcp, tool, review_id, ref):
        mcp.space_client.set_merge_request_state = AsyncMock(return_value=None)
        result = await getattr(mcp, tool)("proj", review_id)
        assert mcp.space_client.set_merge_request_state.await_args.args[:2] == ("proj", ref)
        assert f"`{review_id}`" in result


class TestPatchMergeRequest:

    async def test_patch_merge_request_tool(self, mcp):
        mcp.space_client.edit_merge_request = AsyncMock(return_value=make_mr(number=194108, title="New title"))
        result = await mcp.patch_merge_request("ij", "194108", title="New title")
        mcp.space_client.edit_merge_request.assert_awaited_once_with(
            project="ij", ref=ReviewRef(number=194108), title="New title", description=None
        )
        assert "New title" in result
        assert "194108" in result

    async def test_patch_merge_request_passes_description(self, mcp):
        mcp.space_client.edit_merge_request = AsyncMock(return_value=make_mr(number=1))
        await mcp.patch_merge_request("ij", "1", description="")
        mcp.space_client.edit_merge_request.assert_awaited_once_with(
            project="ij", ref=ReviewRef(number=1), title=None, description=""
        )

    async def test_patch_merge_request_validation_error_surfaced(self, mcp):
        mcp.space_client.edit_merge_request = AsyncMock(
            side_effect=ValueError("nothing to edit: pass title and/or description")
        )
        result = await mcp.patch_merge_request("ij", "194108")
        assert "nothing to edit" in result.lower()

    async def test_patch_merge_request_partial_edit_labeled(self, mcp):
        from space.client import MergeRequestEditError
        mcp.space_client.edit_merge_request = AsyncMock(
            side_effect=MergeRequestEditError(["title"], RuntimeError("boom"))
        )
        result = await mcp.patch_merge_request("ij", "1", title="T", description="D")
        assert "Partial edit" in result
        assert "title" in result


# review_id parsing ====================================================================================================

_PARSING_TOOLS = {
    "get_merge_request": lambda mcp, rid: mcp.get_merge_request("ij", "ultimate", rid),
    "get_merge_request_timeline": lambda mcp, rid: mcp.get_merge_request_timeline("ij", "ultimate", rid),
    "patch_merge_request": lambda mcp, rid: mcp.patch_merge_request("ij", rid, title="T"),
    "post_close_merge_request": lambda mcp, rid: mcp.post_close_merge_request("ij", rid),
    "post_reopen_merge_request": lambda mcp, rid: mcp.post_reopen_merge_request("ij", rid),
    "post_merge_request_comment": lambda mcp, rid: mcp.post_merge_request_comment("ij", rid, "hi"),
    "post_code_discussion": lambda mcp, rid: mcp.post_code_discussion("ij", rid, "repo", "abc", "f.py", 1, "t"),
    "post_delete_merge_request": lambda mcp, rid: mcp.post_delete_merge_request("ij", rid),
    "get_patronus_runs": lambda mcp, rid: mcp.get_patronus_runs("ij", rid),
    "put_patronus_dry_run": lambda mcp, rid: mcp.put_patronus_dry_run("ij", rid),
}


@pytest.mark.parametrize("tool", sorted(_PARSING_TOOLS))
@pytest.mark.parametrize(
    ("review_id", "expected"),
    [
        ("0", "**Error:** merge request numbers start at 1, got '0'"),
        ("", "**Error:** empty merge request reference"),
    ],
    ids=["zero", "empty"],
)
async def test_parse_errors_are_reported(mcp, tool, review_id, expected):
    assert await _PARSING_TOOLS[tool](mcp, review_id) == expected
    assert mcp.space_client.method_calls == []
    assert mcp.patronus_client.method_calls == []


async def test_review_id_descriptions_document_id_refs():
    tools = {t.name: t for t in await SpaceMCP(token="test-token").list_tools()}
    for name in _PARSING_TOOLS:
        description = tools[name].description or ""
        assert '"id:<internal id>"' in description, name
        assert "all-digit" in description, name


# Server lifecycle =====================================================================================================


class TestServerLifecycle:

    async def test_failed_warmup_cancels_the_other_and_closes_both_clients(self, monkeypatch):
        from space.client import SpaceClient
        from space.patronus import PatronusClient

        record: list[str] = []

        async def failing_warmup(self):
            raise RuntimeError("boom")

        async def blocked_warmup(self):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                record.append("patronus warmup cancelled")
                raise

        async def space_aclose(self):
            record.append("space closed")

        async def patronus_aclose(self):
            record.append("patronus closed")

        monkeypatch.setattr(SpaceClient, "warmup", failing_warmup)
        monkeypatch.setattr(PatronusClient, "warmup", blocked_warmup)
        monkeypatch.setattr(SpaceClient, "aclose", space_aclose)
        monkeypatch.setattr(PatronusClient, "aclose", patronus_aclose)

        with pytest.raises(RuntimeError, match="boom"):
            async with SpaceMCP(token="test-token"):
                pass

        assert record == ["patronus warmup cancelled", "patronus closed", "space closed"]
