"""Tests for Patronus domain model dataclasses."""

from datetime import datetime, timezone

from space.models import (
    AttemptDetails,
    FailedBuild,
    FailedTest,
    PatronusCheckConfig,
    PatronusCheckRun,
    PatronusCheckRunAttempt,
    PatronusRun,
    Problem,
    RunStatus,
)
from space.models.patronus import iso_local

from tests.factories import make_check_config, make_check_run, make_dt, make_run


class TestPatronusCheckConfig:

    def test_from_api(self):
        config = PatronusCheckConfig.from_api({
            "name": "Compile All",
            "buildConfigurationId": "compile_all_id",
            "buildConfigurationName": "Compile All Build",
            "buildConfigurationUrl": "https://tc.example.com/compile",
            "buildConfigurationProjectName": "Project / Build",
            "attemptLimit": 3,
        })
        assert config.name == "Compile All"
        assert config.build_configuration_id == "compile_all_id"
        assert config.build_configuration_name == "Compile All Build"
        assert config.build_configuration_url == "https://tc.example.com/compile"
        assert config.project_name == "Project / Build"
        assert config.attempt_limit == 3


class TestPatronusCheckRunAttempt:

    def test_from_api_full(self):
        attempt = PatronusCheckRunAttempt.from_api({
            "id": "att-1",
            "number": 0,
            "status": "SUCCESS",
            "buildId": "98765",
            "buildUrl": "https://tc.example.com/build/98765",
            "startedAt": "2026-01-15T08:00:06Z",
            "finishedAt": "2026-01-15T08:07:28Z",
            "failedTestsNumber": 0,
            "failedBuildsNumber": 0,
        })
        assert attempt.id == "att-1"
        assert attempt.number == 0
        assert attempt.status == RunStatus.SUCCESS
        assert attempt.build_id == "98765"
        assert attempt.build_url == "https://tc.example.com/build/98765"
        assert attempt.started_at == datetime(2026, 1, 15, 8, 0, 6, tzinfo=timezone.utc)
        assert attempt.finished_at == datetime(2026, 1, 15, 8, 7, 28, tzinfo=timezone.utc)

    def test_from_api_running(self):
        attempt = PatronusCheckRunAttempt.from_api({
            "id": "att-2",
            "number": 0,
            "status": "RUNNING",
            "buildId": "98766",
            "buildUrl": "https://tc.example.com/build/98766",
            "startedAt": "2026-01-15T08:00:06Z",
            "finishedAt": None,
            "failedTestsNumber": None,
            "failedBuildsNumber": None,
        })
        assert attempt.finished_at is None
        assert attempt.failed_tests_count is None

    def test_from_api_normalizes_build_id_to_str(self):
        attempt = PatronusCheckRunAttempt.from_api({
            "id": "att-3",
            "number": 0,
            "status": "SUCCESS",
            "buildId": 98765,  # int from API
        })
        assert attempt.build_id == "98765"
        assert isinstance(attempt.build_id, str)


class TestFailedTest:

    def test_from_api(self):
        ft = FailedTest.from_api({
            "name": "com.example.FooTest.test something important",
            "url": "https://tc.example.com/test/123",
        })
        assert ft.name == "com.example.FooTest.test something important"
        assert ft.url == "https://tc.example.com/test/123"

    def test_from_api_no_url(self):
        ft = FailedTest.from_api({"name": "test_foo"})
        assert ft.url is None


class TestFailedBuild:

    def test_from_api(self):
        fb = FailedBuild.from_api({
            "buildId": "98770",
            "buildUrl": "https://tc.example.com/build/98770",
            "buildConfigurationId": "test_Build",
            "buildConfigurationUrl": "https://tc.example.com/buildConfiguration/test_Build",
            "buildConfigurationName": "Unit Tests",
            "fullProjectName": "Project / Tests",
            "isFailedToStart": False,
            "problems": [
                {"details": "Process exited with code 1"},
                {"details": "1 failed test detected"},
            ],
        })
        assert fb.build_id == "98770"
        assert fb.build_configuration_name == "Unit Tests"
        assert fb.is_failed_to_start is False
        assert fb.problems == ("Process exited with code 1", "1 failed test detected")


class TestPatronusCheckRunFromApi:

    def test_from_api_with_null_queued_at(self):
        data = {
            "id": "check-1", "name": "Compile All",
            "buildConfigurationId": "bc-1", "buildConfigurationName": "Compile All Build",
            "buildConfigurationProjectName": "Project", "attemptLimit": 3,
            "status": "PENDING", "queuedAt": None,
            "startedAt": None, "finishedAt": None, "attempts": [],
        }
        check = PatronusCheckRun.from_api(data)
        assert check.id == "check-1"
        assert check.status == RunStatus.PENDING
        assert check.queued_at is None
        assert check.started_at is None


class TestPatronusRunFromApi:

    async def test_from_api_with_null_start_datetime(self, test_accounts):
        data = {
            "id": "run-1", "name": "Test run", "status": "PENDING",
            "pushMode": "DRY_RUN", "sourceBranch": "feature",
            "targetBranch": "main", "repository": "repo",
            "owner": {"id": "user-azhukova"},  # matches test_accounts cache
            "startDateTime": None, "type": "SAFE_PUSH",
        }
        # client unused when SpaceAccount cache is pre-populated by test_accounts fixture
        run = await PatronusRun.from_api(data, None)
        assert run.id == "run-1"
        assert run.status == RunStatus.PENDING
        assert run.started_at is None


# iso_local helper =====


class TestIsoLocal:

    def test_none_returns_none(self):
        assert iso_local(None) is None

    def test_utc_datetime(self):
        dt = datetime(2026, 1, 16, 10, 0, tzinfo=timezone.utc)
        result = iso_local(dt)
        # Result should be a valid ISO 8601 string with timezone info
        parsed = datetime.fromisoformat(result)
        assert parsed == dt

    def test_preserves_value(self):
        dt = make_dt(hour=8, minute=30)
        result = iso_local(dt)
        assert result is not None
        parsed = datetime.fromisoformat(result)
        assert parsed == dt


# dump() methods =====


class TestPatronusRunDump:

    def test_basic_fields(self):
        run = make_run()
        d = run.dump()
        assert d["name"] == "Fix auth (dry run)"
        assert d["status"] == "SUCCESSFUL"
        assert d["mode"] == "DRY_RUN"
        assert d["owner"] == "@azhukova (Anna Zhukova)"

    def test_branch_pair_embedded(self):
        run = make_run()
        d = run.dump()
        assert d["source-branch"] == "refs/patronus/safepush/abc"
        assert d["target-branch"] == "master"
        assert d["repository"] == "ultimate"

    def test_urls(self):
        run = make_run()
        d = run.dump()
        assert d["patronus-url"] == f"https://patronus.labs.jb.gg/robot/{run.id}"
        assert d["space-mr-url"] == "https://jetbrains.team/p/IJ/reviews/188120/timeline"

    def test_timestamps_present(self):
        run = make_run()
        d = run.dump()
        assert d["started-at"] is not None
        assert d["finished-at"] is not None

    def test_none_timestamps(self):
        run = make_run(started_at=None, finished_at=None)
        d = run.dump()
        assert d["started-at"] is None
        assert d["finished-at"] is None


class TestPatronusCheckRunDump:

    def test_basic_fields(self):
        check = make_check_run("Compile All", RunStatus.SUCCESS)
        d = check.dump()
        assert d["status"] == "SUCCESS"
        assert d["name"] == "Compile All"
        assert d["build-config-url"] == "https://tc.example.com/Compile All"


class TestProblemDump:

    def test_with_details(self):
        p = Problem(title="3 tests failed", details="com.example.FooTest")
        d = p.dump()
        assert d == {"title": "3 tests failed", "details": "com.example.FooTest"}

    def test_without_details(self):
        p = Problem(title="Build failed")
        d = p.dump()
        assert d == {"title": "Build failed", "details": None}


class TestAttemptDetailsDump:

    def test_with_failed_tests(self):
        attempt = AttemptDetails(
            id="att-1", number=0, status=RunStatus.FAILURE,
            failed_tests=(FailedTest(name="test_foo"), FailedTest(name="test_bar")),
        )
        d = attempt.dump()
        assert d["failed-tests"] == ["test_foo", "test_bar"]

    def test_with_failed_builds(self):
        attempt = AttemptDetails(
            id="att-1", number=0, status=RunStatus.FAILURE,
            failed_builds=(FailedBuild(
                build_id="1", build_url=None, build_configuration_id="bc",
                build_configuration_url=None, build_configuration_name="Unit Tests",
                full_project_name="Project", is_failed_to_start=False,
                problems=("Exit code 1",),
            ),),
        )
        d = attempt.dump()
        assert len(d["build-problems"]) == 1

    def test_empty_when_no_failures(self):
        attempt = AttemptDetails(id="att-1", number=0, status=RunStatus.SUCCESS)
        d = attempt.dump()
        assert d == {}

    def test_skips_builds_without_problems(self):
        attempt = AttemptDetails(
            id="att-1", number=0, status=RunStatus.FAILURE,
            failed_builds=(FailedBuild(
                build_id="1", build_url=None, build_configuration_id="bc",
                build_configuration_url=None, build_configuration_name="Unit Tests",
                full_project_name="Project", is_failed_to_start=False,
                problems=(),
            ),),
        )
        d = attempt.dump()
        assert "build-problems" not in d


class TestFailedBuildDump:

    def test_basic_fields(self):
        fb = FailedBuild(
            build_id="1", build_url="https://tc.example.com/build/1",
            build_configuration_id="bc", build_configuration_url=None,
            build_configuration_name="Unit Tests", full_project_name="Project",
            is_failed_to_start=False, problems=("Exit code 1", "OOM"),
        )
        d = fb.dump()
        assert d == {"config": "Unit Tests", "problems": ["Exit code 1", "OOM"]}

    def test_none_config_name(self):
        fb = FailedBuild(
            build_id="1", build_url=None, build_configuration_id="bc",
            build_configuration_url=None, build_configuration_name="",
            full_project_name="", is_failed_to_start=False, problems=(),
        )
        d = fb.dump()
        assert d["config"] is None
