"""Tests for MCP markdown formatting functions."""

from __future__ import annotations

from datetime import datetime, timezone

from space.models import (
    Attachment,
    AttemptDetails,
    BranchPair,
    CodeDiscussion,
    Comment,
    FailedBuild,
    FailedTest,
    FileAttachment,
    ImageAttachment,
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
from space.mcp.format import (
    format_merge_request,
    format_create_result,
    format_discussions,
    format_merge_request_list,
    format_patronus_runs,
    format_patronus_run_details,
    _human_size,
)


# Helpers =====


def _account(name: str = "Anna Zhukova", username: str = "azhukova") -> SpaceAccount:
    first, last = (name.split(" ", 1) + [""])[:2]
    return SpaceAccount(id=f"id-{username}", username=username, email=f"{username}@test.com", first_name=first, last_name=last)


def _dt(year: int = 2026, month: int = 1, day: int = 16, hour: int = 10, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _mr(**overrides) -> MergeRequest:
    defaults = dict(
        id="123456", number=188120, title="Fix authentication bug",
        state=MRState.OPENED, created_at=_dt(),
        description=None, created_by=_account(),
        participants=(Reviewer(user=_account("John Doe", "jdoe"), role=ReviewRole.REVIEWER, state=ReviewState.PENDING),),
        branch_pairs=(BranchPair(source_branch="azhukova/fix-auth", target_branch="main", repository="ultimate"),),
    )
    defaults.update(overrides)
    return MergeRequest(**defaults)


def _run(**overrides) -> PatronusRun:
    defaults = dict(
        id="cc448634-880e-411f-9ee6-347e9a6087ac", name="Fix auth (dry run)",
        status=RunStatus.SUCCESSFUL, push_mode=PushMode.DRY_RUN,
        branch_pair=BranchPair(source_branch="refs/patronus/safepush/abc", target_branch="master", repository="ultimate"),
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


def _check_run(name: str = "Compile All", status: RunStatus = RunStatus.SUCCESS) -> PatronusCheckRun:
    return PatronusCheckRun(
        id=f"check-{name}", config=_check_config(name), status=status,
        queued_at=_dt(hour=8), started_at=_dt(hour=8, minute=1), finished_at=_dt(hour=8, minute=5),
        skip_reason=None, attempts=(),
    )


# MR formatting =====


class TestFormatMergeRequest:

    def test_basic_structure(self):
        result = format_merge_request(_mr())
        assert "# [MR 188120] Fix authentication bug" in result
        assert "**State:** Opened" in result
        assert "`azhukova/fix-auth` -> `main`" in result

    def test_reviewer_table(self):
        result = format_merge_request(_mr())
        assert "| Reviewer | State |" in result
        assert "John Doe" in result
        assert "Pending" in result

    def test_no_description(self):
        result = format_merge_request(_mr(description=None))
        lines = result.split("\n")
        assert lines[1] == ""
        assert lines[2].startswith("**State:**")

    def test_with_description(self):
        result = format_merge_request(_mr(description="This fixes the auth flow."))
        assert "This fixes the auth flow." in result
        lines = result.split("\n")
        title_idx = next(i for i, l in enumerate(lines) if l.startswith("# [MR"))
        desc_idx = next(i for i, l in enumerate(lines) if "auth flow" in l)
        state_idx = next(i for i, l in enumerate(lines) if l.startswith("**State:**"))
        assert title_idx < desc_idx < state_idx


class TestFormatCreateResult:

    def test_basic_structure(self):
        result = format_create_result(_mr(number=194200, title="New feature",
            branch_pairs=(BranchPair("azhukova/new-feature", "master", "ultimate"),)))
        assert "Merge request created." in result
        assert "**#194200** New feature" in result
        assert "`azhukova/new-feature` -> `master` (ultimate)" in result

    def test_no_branch_pairs(self):
        result = format_create_result(_mr(number=1, title="Test", branch_pairs=()))
        assert "**#1** Test" in result


# Timeline formatting =====


class TestFormatDiscussions:

    def test_empty(self):
        assert format_discussions([]) == "No timeline items."

    def test_message_with_day_header(self):
        items = [TimelineMessage(
            event_class=TimelineEventClass.MC_MESSAGE, text="created the merge request",
            author=_account(), created_at=_dt(), attachments=(), thread_replies=(),
        )]
        result = format_discussions(items)
        assert "## " in result
        assert "2026" in result
        assert "**Anna Zhukova**" in result
        assert "created the merge request" in result

    def test_code_discussion(self):
        items = [CodeDiscussion(
            id="d1", file="/src/auth.py", line=42, resolved=True,
            comments=(
                Comment(text="Fix this", author=_account("John", "john"), created_at=_dt(), attachments=()),
                Comment(text="Done", author=_account(), created_at=_dt(minute=5), attachments=()),
            ),
        )]
        result = format_discussions(items)
        assert "`/src/auth.py:42`" in result
        assert "Fix this" in result
        assert "Done" in result

    def test_resolved_discussion_formatting(self):
        items = [CodeDiscussion(
            id="d1", file="/src/foo.py", line=10, resolved=True,
            comments=(
                Comment(text="Question", author=_account("John", "john"), created_at=_dt(), attachments=()),
                Comment(text="User resolved the discussion", author=_account(), created_at=_dt(minute=5), attachments=()),
            ),
        )]
        result = format_discussions(items)
        assert "*resolved the discussion*" in result

    def test_message_with_thread_replies(self):
        items = [TimelineMessage(
            event_class=TimelineEventClass.MC_MESSAGE, text="started a dry run",
            author=_account(), created_at=_dt(), attachments=(),
            thread_replies=(
                Comment(text="Dry Run started", author=SpaceApp(app_name="Patronus"), created_at=_dt(minute=1), attachments=()),
                Comment(text="Dry Run **success**", author=SpaceApp(app_name="Patronus"), created_at=_dt(minute=2), attachments=()),
            ),
        )]
        result = format_discussions(items)
        assert "started a dry run" in result
        assert "  - **Patronus**: Dry Run started" in result
        assert "  - **Patronus**: Dry Run **success**" in result

    def test_message_with_attachments(self):
        items = [TimelineMessage(
            event_class=TimelineEventClass.MC_MESSAGE, text="Here is the file",
            author=_account(), created_at=_dt(),
            attachments=(FileAttachment(id="file-001", name="report.txt", size_bytes=4096, download_url="https://jetbrains.team/d/file-001"),),
            thread_replies=(),
        )]
        result = format_discussions(items)
        assert "report.txt" in result
        assert "4.0 KB" in result
        assert "file-001" in result


# MR list =====


class TestFormatMergeRequestList:

    def test_empty(self):
        assert format_merge_request_list([]) == "No merge requests found."

    def test_table_structure(self):
        result = format_merge_request_list([_mr(title="Fix bug")])
        assert "| Title | State | Author | Branch |" in result
        assert "Fix bug" in result
        assert "`azhukova/fix-auth` -> `main`" in result


# Patronus formatting =====


class TestFormatPatronusRuns:

    def test_empty(self):
        assert format_patronus_runs([], {}) == "No Patronus runs found."

    def test_table_with_run_ids(self):
        run = _run()
        commits = {run.id: "abc12345"}
        result = format_patronus_runs([run], commits)
        assert "| Run ID |" in result
        assert "| Status |" in result
        assert "SUCCESSFUL" in result
        assert "DRY_RUN" in result
        assert "cc448634" in result

    def test_commit_hash_displayed(self):
        run = _run()
        commits = {run.id: "fe9f53cb"}
        result = format_patronus_runs([run], commits)
        assert "`fe9f53cb`" in result

    def test_none_commit_shows_question_mark(self):
        run = _run()
        commits = {run.id: None}
        result = format_patronus_runs([run], commits)
        assert "?" in result

    def test_sorted_newest_first(self):
        older = _run(id="aaa", started_at=_dt(hour=6), finished_at=_dt(hour=7))
        newer = _run(id="bbb", started_at=_dt(hour=9), finished_at=_dt(hour=10))
        result = format_patronus_runs([older, newer], {"aaa": None, "bbb": None})
        bbb_pos = result.index("bbb")
        aaa_pos = result.index("aaa")
        assert bbb_pos < aaa_pos

    def test_still_running(self):
        run = _run(status=RunStatus.RUNNING, finished_at=None)
        result = format_patronus_runs([run], {run.id: None})
        assert "*(still running)*" in result

    def test_still_queued(self):
        run = _run(status=RunStatus.PENDING, finished_at=None)
        result = format_patronus_runs([run], {run.id: None})
        assert "*(still queued)*" in result


class TestFormatPatronusRunDetails:

    def test_basic_structure(self):
        problems = (Problem(check=_check_config("Unit Tests"), title="3 tests failed in Unit Tests", details="Failures in `com.example.FooTest`"),)
        result = format_patronus_run_details(_run(), [_check_run(), _check_run("Unit Tests", RunStatus.FAILURE)], problems)
        assert "# Fix auth (dry run)" in result
        assert "**Status:** SUCCESSFUL" in result
        assert "**Mode:** DRY_RUN" in result
        assert "patronus.labs.jb.gg" in result

    def test_tc_checks_table(self):
        checks = [_check_run(), _check_run("Unit Tests", RunStatus.FAILURE)]
        result = format_patronus_run_details(_run(), checks, ())
        assert "## TeamCity Checks" in result
        assert "Compile All" in result
        assert "Unit Tests" in result

    def test_problems_section(self):
        problems = (Problem(check=_check_config("Unit Tests"), title="3 tests failed in Unit Tests", details="Failures in `com.example.FooTest`"),)
        result = format_patronus_run_details(_run(), [], problems)
        assert "## Problems" in result
        assert "3 tests failed in Unit Tests" in result
        assert "Failures in `com.example.FooTest`" in result

    def test_no_problems(self):
        result = format_patronus_run_details(_run(), [], ())
        assert "None" in result

    def test_empty_tc_checks(self):
        result = format_patronus_run_details(_run(), [], ())
        assert "No checks." in result

    def test_failed_checks_section(self):
        attempt = AttemptDetails(
            id="att-1", number=0, status=RunStatus.FAILURE, build_id="98770",
            build_url="https://tc.example.com/build/98770",
            started_at=_dt(hour=8), finished_at=_dt(hour=8, minute=7),
            failed_tests=(FailedTest(name="com.example.FooTest.test something important"),),
            failed_builds=(FailedBuild(
                build_id="98770", build_url="https://tc.example.com/build/98770",
                build_configuration_id="test_Build", build_configuration_url=None,
                build_configuration_name="Unit Tests", full_project_name="Project / Tests",
                is_failed_to_start=False, problems=("Process exited with code 1 (Step: test)", "1 failed test detected"),
            ),),
        )
        result = format_patronus_run_details(_run(), [], (), attempt_details={"Unit Tests": attempt})
        assert "## Failed Checks" in result
        assert "### Unit Tests" in result
        assert "com.example.FooTest.test something important" in result
        assert "Process exited with code 1 (Step: test)" in result


class TestHumanSize:

    def test_bytes(self):
        assert _human_size(500) == "500 B"

    def test_kilobytes(self):
        assert _human_size(4096) == "4.0 KB"

    def test_megabytes(self):
        assert _human_size(1048576) == "1.0 MB"

    def test_none(self):
        assert _human_size(None) == ""

    def test_zero(self):
        assert _human_size(0) == "0 B"
