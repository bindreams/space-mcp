"""Tests for MCP YAML and Markdown formatting functions."""

from __future__ import annotations

from space.models import (
    AttemptDetails,
    BranchPair,
    CodeDiscussion,
    Comment,
    FailedBuild,
    FailedTest,
    FileAttachment,
    PatronusCheckRun,
    Problem,
    RunStatus,
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
)

from tests.factories import make_account, make_check_config, make_check_run, make_dt, make_mr, make_run

# MR formatting ========================================================================================================


class TestFormatMergeRequest:

    def test_yaml_output(self):
        result = format_merge_request(make_mr())
        assert result.startswith("merge-request:")
        assert "number: 188120" in result
        assert "title: Fix authentication bug" in result
        assert "state: Opened" in result

    def test_includes_branch_info(self):
        result = format_merge_request(make_mr())
        assert "source-branch: azhukova/fix-auth" in result
        assert "target-branch: main" in result
        assert "repository: ultimate" in result

    def test_includes_reviewers(self):
        result = format_merge_request(make_mr())
        assert "reviewers:" in result
        assert "name:" in result
        assert "state: Pending" in result

    def test_no_description(self):
        result = format_merge_request(make_mr(description=None))
        # description key should be omitted (None stripped by dump_yaml)
        assert "description:" not in result

    def test_with_description(self):
        result = format_merge_request(make_mr(description="This fixes the auth flow."))
        assert "description: This fixes the auth flow." in result

    def test_author_field(self):
        result = format_merge_request(make_mr())
        assert "author:" in result


class TestFormatCreateResult:

    def test_yaml_output(self):
        result = format_create_result(
            make_mr(
                number=194200,
                title="New feature",
                branch_pair=BranchPair("azhukova/new-feature", "master", "ultimate")
            )
        )
        assert "create-success: true" in result
        assert "merge-request:" in result
        assert "number: 194200" in result
        assert "title: New feature" in result
        assert "source-branch: azhukova/new-feature" in result
        assert "target-branch: master" in result

    def test_no_state_or_author(self):
        result = format_create_result(make_mr())
        assert "state:" not in result
        assert "author:" not in result
        assert "reviewers:" not in result

    def test_no_branch_pair(self):
        result = format_create_result(make_mr(number=1, title="Test", branch_pair=None))
        assert "number: 1" in result
        assert "title: Test" in result

    def test_description_excluded_even_when_present(self):
        result = format_create_result(make_mr(description="Some description"))
        assert "description" not in result


# Timeline formatting ==================================================================================================


class TestFormatDiscussions:

    def test_empty(self):
        assert format_discussions([]) == "No timeline items."

    def test_message_with_day_header(self):
        items = [
            TimelineMessage(
                event_class=TimelineEventClass.MC_MESSAGE,
                text="created the merge request",
                author=make_account(),
                created_at=make_dt(),
                attachments=(),
                thread_replies=(),
            )
        ]
        result = format_discussions(items)
        assert "## " in result
        assert "2026" in result
        assert "**Anna Zhukova**" in result
        assert "created the merge request" in result

    def test_code_discussion(self):
        items = [
            CodeDiscussion(
                id="d1",
                file="/src/auth.py",
                line=42,
                resolved=True,
                comments=(
                    Comment(text="Fix this", author=make_account("John", "john"), created_at=make_dt(), attachments=()),
                    Comment(text="Done", author=make_account(), created_at=make_dt(minute=5), attachments=()),
                ),
            )
        ]
        result = format_discussions(items)
        assert "`/src/auth.py:42`" in result
        assert "Fix this" in result
        assert "Done" in result

    def test_resolved_discussion_formatting(self):
        items = [
            CodeDiscussion(
                id="d1",
                file="/src/foo.py",
                line=10,
                resolved=True,
                comments=(
                    Comment(text="Question", author=make_account("John", "john"), created_at=make_dt(), attachments=()),
                    Comment(
                        text="User resolved the discussion",
                        author=make_account(),
                        created_at=make_dt(minute=5),
                        attachments=()
                    ),
                ),
            )
        ]
        result = format_discussions(items)
        assert "*resolved the discussion*" in result

    def test_message_with_thread_replies(self):
        items = [
            TimelineMessage(
                event_class=TimelineEventClass.MC_MESSAGE,
                text="started a dry run",
                author=make_account(),
                created_at=make_dt(),
                attachments=(),
                thread_replies=(
                    Comment(
                        text="Dry Run started",
                        author=SpaceApp(app_name="Patronus"),
                        created_at=make_dt(minute=1),
                        attachments=()
                    ),
                    Comment(
                        text="Dry Run **success**",
                        author=SpaceApp(app_name="Patronus"),
                        created_at=make_dt(minute=2),
                        attachments=()
                    ),
                ),
            )
        ]
        result = format_discussions(items)
        assert "started a dry run" in result
        assert "  - **Patronus**: Dry Run started" in result
        assert "  - **Patronus**: Dry Run **success**" in result

    def test_message_with_attachments(self):
        items = [
            TimelineMessage(
                event_class=TimelineEventClass.MC_MESSAGE,
                text="Here is the file",
                author=make_account(),
                created_at=make_dt(),
                attachments=(
                    FileAttachment(
                        id="file-001",
                        name="report.txt",
                        size_bytes=4096,
                        download_url="https://jetbrains.team/d/file-001"
                    ),
                ),
                thread_replies=(),
            )
        ]
        result = format_discussions(items)
        assert "report.txt" in result
        assert "4.0 KB" in result
        assert "file-001" in result


# MR list ==============================================================================================================


class TestFormatMergeRequestList:

    def test_empty(self):
        assert format_merge_request_list([]) == "No merge requests found."

    def test_yaml_output(self):
        result = format_merge_request_list([make_mr(title="Fix bug")])
        assert "merge-requests:" in result
        assert "title: Fix bug" in result
        assert "state: Opened" in result

    def test_includes_number(self):
        result = format_merge_request_list([make_mr(number=194108)])
        assert "number: 194108" in result

    def test_includes_branch(self):
        result = format_merge_request_list([make_mr()])
        assert "source-branch: azhukova/fix-auth" in result
        assert "target-branch: main" in result


# Patronus formatting ==================================================================================================


class TestFormatPatronusRuns:

    def test_empty(self):
        assert format_patronus_runs([], {}) == "No Patronus runs found."

    def test_yaml_with_run_ids(self):
        run = make_run()
        commits = {run.id: "abc12345"}
        result = format_patronus_runs([run], commits)
        assert "patronus-runs:" in result
        assert "run-id: cc448634-880e-411f-9ee6-347e9a6087ac" in result
        assert "status: SUCCESSFUL" in result
        assert "mode: DRY_RUN" in result

    def test_commit_hash_displayed(self):
        run = make_run()
        commits = {run.id: "fe9f53cb"}
        result = format_patronus_runs([run], commits)
        assert "commit: fe9f53cb" in result

    def test_none_commit_omitted(self):
        run = make_run()
        commits = {run.id: None}
        result = format_patronus_runs([run], commits)
        assert "commit:" not in result

    def test_empty_string_commit_omitted(self):
        run = make_run()
        commits = {run.id: ""}
        result = format_patronus_runs([run], commits)
        assert "commit:" not in result

    def test_sorted_newest_first(self):
        older = make_run(id="aaa", started_at=make_dt(hour=6), finished_at=make_dt(hour=7))
        newer = make_run(id="bbb", started_at=make_dt(hour=9), finished_at=make_dt(hour=10))
        result = format_patronus_runs([older, newer], {"aaa": None, "bbb": None})
        bbb_pos = result.index("bbb")
        aaa_pos = result.index("aaa")
        assert bbb_pos < aaa_pos

    def test_finished_at_displayed(self):
        run = make_run()
        result = format_patronus_runs([run], {run.id: None})
        assert "finished-at:" in result

    def test_failing_status_with_checks(self):
        run = make_run(status=RunStatus.RUNNING, finished_at=None)
        checks = {run.id: [make_check_run("Compile", RunStatus.SUCCESS), make_check_run("Tests", RunStatus.FAILURE)]}
        result = format_patronus_runs([run], {run.id: None}, checks=checks)
        assert "FAILING" in result

    def test_full_run_id_displayed(self):
        run = make_run()
        result = format_patronus_runs([run], {run.id: "abc12345"})
        assert "cc448634-880e-411f-9ee6-347e9a6087ac" in result

    def test_running_without_failed_checks(self):
        run = make_run(status=RunStatus.RUNNING, finished_at=None)
        checks = {run.id: [make_check_run("Compile", RunStatus.RUNNING)]}
        result = format_patronus_runs([run], {run.id: None}, checks=checks)
        assert "RUNNING" in result
        assert "FAILING" not in result

    def test_run_with_none_started_at(self):
        run = make_run(started_at=None, finished_at=None, status=RunStatus.PENDING)
        result = format_patronus_runs([run], {run.id: None})
        assert "status: PENDING" in result

    def test_sorted_with_none_started_at_last(self):
        queued = make_run(id="aaa", started_at=None, finished_at=None, status=RunStatus.PENDING)
        running = make_run(id="bbb", started_at=make_dt(hour=9), finished_at=None, status=RunStatus.RUNNING)
        result = format_patronus_runs([queued, running], {"aaa": None, "bbb": None})
        bbb_pos = result.index("bbb")
        aaa_pos = result.index("aaa")
        assert bbb_pos < aaa_pos  # running sorts before queued (not-yet-started)


class TestFormatPatronusRunDetails:

    def test_basic_structure(self):
        problems = (
            Problem(
                check=make_check_config("Unit Tests"),
                title="3 tests failed in Unit Tests",
                details="Failures in `com.example.FooTest`"
            ),
        )
        result = format_patronus_run_details(
            make_run(), [make_check_run(), make_check_run("Unit Tests", RunStatus.FAILURE)], problems
        )
        assert "patronus-run:" in result
        assert "name: Fix auth (dry run)" in result
        assert "status: SUCCESSFUL" in result
        assert "mode: DRY_RUN" in result
        assert "patronus-url:" in result

    def test_failing_status(self):
        run = make_run(status=RunStatus.RUNNING, finished_at=None)
        checks = [make_check_run("Compile", RunStatus.SUCCESS), make_check_run("Tests", RunStatus.FAILURE)]
        result = format_patronus_run_details(run, checks, ())
        assert "status: FAILING" in result

    def test_tc_checks_section(self):
        checks = [make_check_run(), make_check_run("Unit Tests", RunStatus.FAILURE)]
        result = format_patronus_run_details(make_run(), checks, ())
        assert "teamcity-checks:" in result
        assert "summary:" in result
        assert "Compile All" in result
        assert "Unit Tests" in result

    def test_problems_section(self):
        problems = (
            Problem(
                check=make_check_config("Unit Tests"),
                title="3 tests failed in Unit Tests",
                details="Failures in `com.example.FooTest`"
            ),
        )
        result = format_patronus_run_details(make_run(), [], problems)
        assert "problems:" in result
        assert "3 tests failed in Unit Tests" in result

    def test_no_problems(self):
        result = format_patronus_run_details(make_run(), [], ())
        assert "problems:" in result

    def test_empty_tc_checks(self):
        result = format_patronus_run_details(make_run(), [], ())
        assert "no checks configured" in result

    def test_failed_check_inline_details(self):
        attempt = AttemptDetails(
            id="att-1",
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
                    build_url="https://tc.example.com/build/98770",
                    build_configuration_id="test_Build",
                    build_configuration_url=None,
                    build_configuration_name="Unit Tests",
                    full_project_name="Project / Tests",
                    is_failed_to_start=False,
                    problems=("Process exited with code 1 (Step: test)", "1 failed test detected"),
                ),
            ),
        )
        checks = [make_check_run("Unit Tests", RunStatus.FAILURE)]
        result = format_patronus_run_details(make_run(), checks, (), attempt_details={"Unit Tests": attempt})
        # Unified list — no separate failed-checks section
        assert "failed-checks:" not in result
        assert "com.example.FooTest.test something important" in result
        assert "Process exited with code 1 (Step: test)" in result
        assert "test-failures:" in result
        assert "build-failures:" in result

    def test_skipped_check_in_output(self):
        skipped = PatronusCheckRun(
            id="check-skipped",
            config=make_check_config(".NET Chain"),
            status=RunStatus.SKIPPED,
            queued_at=make_dt(hour=8),
            started_at=None,
            finished_at=None,
            skip_reason="No changes in /net/**",
            attempts=(),
        )
        result = format_patronus_run_details(make_run(), [skipped], ())
        assert "status: SKIPPED" in result
        assert "skip-reason:" in result
        assert "1 skipped" in result
