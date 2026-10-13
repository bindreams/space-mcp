"""Tests for Patronus domain model dataclasses."""

import logging
from datetime import datetime, timezone

import pytest

from space.models import (
    AttemptDetails,
    AttemptStatus,
    CheckStatus,
    FailedBuild,
    FailedTest,
    PatronusCheckConfig,
    PatronusCheckRun,
    PatronusCheckRunAttempt,
    PatronusRun,
    Problem,
    RunStatus,
)
from space.models import enums
from space.models.patronus import iso_local

from tests.factories import make_check_config, make_check_run, make_dt, make_run
from tests.sample_responses import SAMPLE_ATTEMPT_DETAILS, wire_attempt, wire_check, wire_run


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
        assert attempt.status == AttemptStatus.SUCCESS
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
            "id": "check-1",
            "name": "Compile All",
            "buildConfigurationId": "bc-1",
            "buildConfigurationName": "Compile All Build",
            "buildConfigurationProjectName": "Project",
            "attemptLimit": 3,
            "status": "QUEUED",
            "queuedAt": None,
            "startedAt": None,
            "finishedAt": None,
            "attempts": [],
        }
        check = PatronusCheckRun.from_api(data)
        assert check.id == "check-1"
        assert check.status == CheckStatus.QUEUED
        assert check.queued_at is None
        assert check.started_at is None


class TestPatronusRunFromApi:

    async def test_from_api_with_null_start_datetime(self, test_accounts):
        # defensive: Patronus sends a non-null startDateTime, but parsing tolerates null
        data = {
            "id": "run-1",
            "name": "Test run",
            "status": "RUNNING",
            "pushMode": "DRY_RUN",
            "sourceBranch": "feature",
            "targetBranch": "main",
            "repository": "repo",
            "owner": {"id": "user-azhukova"},  # matches test_accounts cache
            "startDateTime": None,
            "type": "SAFE_PUSH",
        }
        # client unused when SpaceAccount cache is pre-populated by test_accounts fixture
        run = await PatronusRun.from_api(data, None)
        assert run.id == "run-1"
        assert run.status == RunStatus.RUNNING
        assert run.started_at is None


# iso_local helper =====================================================================================================


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


# dump() methods =======================================================================================================


class TestPatronusRunDump:

    def test_basic_fields(self):
        run = make_run()
        d = run.dump()
        assert d["name"] == "Fix auth (dry run)"
        assert d["status"] == "SUCCESS"
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
        d = run.dump(patronus_base_url="https://patronus-staging.labs.jb.gg")
        assert d["patronus-url"] == f"https://patronus-staging.labs.jb.gg/robot/{run.id}"
        assert d["space-mr-url"] == "https://jetbrains.team/p/IJ/reviews/188120/timeline"

    def test_default_patronus_url(self):
        run = make_run()
        d = run.dump()
        assert d["patronus-url"] == f"https://patronus.labs.jb.gg/robot/{run.id}"

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
        check = make_check_run("Compile All", CheckStatus.SUCCESS)
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
            id="att-1",
            number=0,
            status=AttemptStatus.FAILURE,
            failed_tests=(FailedTest(name="test_foo"), FailedTest(name="test_bar")),
        )
        d = attempt.dump()
        assert d["test-failures"] == ["test_foo", "test_bar"]

    def test_with_failed_builds(self):
        attempt = AttemptDetails(
            id="att-1",
            number=0,
            status=AttemptStatus.FAILURE,
            failed_builds=(
                FailedBuild(
                    build_id="1",
                    build_url="https://tc.example.com/build/1",
                    build_configuration_id="bc",
                    build_configuration_url=None,
                    build_configuration_name="Unit Tests",
                    full_project_name="Project",
                    is_failed_to_start=False,
                    problems=("Exit code 1", ),
                ),
            ),
        )
        d = attempt.dump()
        assert len(d["build-failures"]) == 1
        assert d["build-failures"][0]["name"] == "Unit Tests"
        assert d["build-failures"][0]["build-url"] == "https://tc.example.com/build/1"
        assert d["build-failures"][0]["problems"] == ["Exit code 1"]

    def test_empty_when_no_failures(self):
        attempt = AttemptDetails(id="att-1", number=0, status=AttemptStatus.SUCCESS)
        d = attempt.dump()
        assert d == {}

    def test_skips_builds_without_problems(self):
        attempt = AttemptDetails(
            id="att-1",
            number=0,
            status=AttemptStatus.FAILURE,
            failed_builds=(
                FailedBuild(
                    build_id="1",
                    build_url=None,
                    build_configuration_id="bc",
                    build_configuration_url=None,
                    build_configuration_name="Unit Tests",
                    full_project_name="Project",
                    is_failed_to_start=False,
                    problems=(),
                ),
            ),
        )
        d = attempt.dump()
        assert "build-failures" not in d


class TestFailedBuildDump:

    def test_basic_fields(self):
        fb = FailedBuild(
            build_id="1",
            build_url="https://tc.example.com/build/1",
            build_configuration_id="bc",
            build_configuration_url=None,
            build_configuration_name="Unit Tests",
            full_project_name="Project",
            is_failed_to_start=False,
            problems=("Exit code 1", "OOM"),
        )
        d = fb.dump()
        assert d == {
            "name": "Unit Tests",
            "build-url": "https://tc.example.com/build/1",
            "problems": ["Exit code 1", "OOM"],
        }

    def test_none_config_name(self):
        fb = FailedBuild(
            build_id="1",
            build_url=None,
            build_configuration_id="bc",
            build_configuration_url=None,
            build_configuration_name="",
            full_project_name="",
            is_failed_to_start=False,
            problems=(),
        )
        d = fb.dump()
        assert d["name"] is None
        assert d["build-url"] is None


# Level-specific status parsing ========================================================================================

_PARSE_CASES = {
    "run": ["RUNNING", "CANCELING", "CANCELED", "SUCCESS", "FAILURE"],
    "check": ["QUEUED", "RUNNING", "FAILURE", "SUCCESS", "CANCELED", "SKIPPED"],
    "attempt": ["RUNNING", "CANCELED", "SUCCESS", "FAILURE"],
}


async def _parse(level: str, raw):
    """Parse a one-field wire object of the given level through its real from_api."""
    if level == "run":
        return await PatronusRun.from_api(wire_run(raw), None)
    if level == "check":
        return PatronusCheckRun.from_api(wire_check(raw))
    return PatronusCheckRunAttempt.from_api(wire_attempt(raw))


class TestWireStatusParsing:

    @pytest.mark.parametrize("wire", _PARSE_CASES["run"])
    async def test_run_parses_every_wire_status(self, test_accounts, wire):
        run = await _parse("run", wire)
        assert run.status.value == wire

    async def test_run_parses_canceled_and_canceling(self, test_accounts):
        canceling = await _parse("run", "CANCELING")
        canceled = await _parse("run", "CANCELED")
        assert canceling.status is enums.RunStatus.CANCELING
        assert canceled.status is enums.RunStatus.CANCELED

    def test_check_parses_queued_canceled_skipped(self):
        response = {"teamCityChecks": [wire_check(v, name=v) for v in ("QUEUED", "CANCELED", "SKIPPED")]}
        checks = [PatronusCheckRun.from_api(c) for c in response["teamCityChecks"]]
        assert [c.status
                for c in checks] == [enums.CheckStatus.QUEUED, enums.CheckStatus.CANCELED, enums.CheckStatus.SKIPPED]
        assert [c.status.value for c in checks] == ["QUEUED", "CANCELED", "SKIPPED"]

    def test_attempt_parses_canceled(self):
        attempt = PatronusCheckRunAttempt.from_api(wire_attempt("CANCELED"))
        assert attempt.status is enums.AttemptStatus.CANCELED

    def test_attempt_details_parse_with_attempt_level(self):
        details = AttemptDetails.from_api(SAMPLE_ATTEMPT_DETAILS)
        assert details.status is enums.AttemptStatus.FAILURE

    async def test_statuses_are_level_typed(self, test_accounts):
        run = await _parse("run", "RUNNING")
        check = PatronusCheckRun.from_api(wire_check("RUNNING", attempts=[wire_attempt("RUNNING")]))
        details = AttemptDetails.from_api(SAMPLE_ATTEMPT_DETAILS)
        assert type(run.status) is enums.RunStatus
        assert type(check.status) is enums.CheckStatus
        assert type(check.attempts[0].status) is enums.AttemptStatus
        assert type(details.status) is enums.AttemptStatus


class TestUnrecognisedStatus:

    @pytest.mark.unrecognised_patronus_status
    @pytest.mark.parametrize(
        "level, enum_name", [("run", "RunStatus"), ("check", "CheckStatus"), ("attempt", "AttemptStatus")]
    )
    async def test_unrecognised_value_is_unknown_and_logged(self, test_accounts, caplog, level, enum_name):
        caplog.set_level(logging.DEBUG, logger="space.models")
        raw = f"NEW_{level.upper()}_STATE"

        first = await _parse(level, raw)
        second = await _parse(level, raw)

        assert first.status is getattr(enums, enum_name).UNKNOWN
        assert second.status is first.status
        records = [r for r in caplog.records if "unrecognised Patronus" in r.getMessage()]
        assert len(records) == 1
        assert records[0].levelno == logging.DEBUG
        assert records[0].name == "space.models"
        assert records[0].getMessage() == f"unrecognised Patronus {enum_name} value {raw!r}"

    @pytest.mark.unrecognised_patronus_status
    @pytest.mark.parametrize(
        "level, enum_name", [("run", "RunStatus"), ("check", "CheckStatus"), ("attempt", "AttemptStatus"),
                             ("details", "AttemptStatus")]
    )
    async def test_missing_status_key_is_unknown_and_logged(self, test_accounts, caplog, level, enum_name):
        caplog.set_level(logging.DEBUG, logger="space.models")
        wire = {"run": wire_run, "check": wire_check, "attempt": wire_attempt}.get(level, None)
        wire = wire("SUCCESS") if wire else dict(SAMPLE_ATTEMPT_DETAILS)
        del wire["status"]

        if level == "run":
            parsed = await PatronusRun.from_api(wire, None)
        elif level == "check":
            parsed = PatronusCheckRun.from_api(wire)
        elif level == "attempt":
            parsed = PatronusCheckRunAttempt.from_api(wire)
        else:
            parsed = AttemptDetails.from_api(wire)

        assert parsed.status is getattr(enums, enum_name).UNKNOWN
        messages = [r.getMessage() for r in caplog.records if "unrecognised Patronus" in r.getMessage()]
        assert messages == [f"unrecognised Patronus {enum_name} value None"]

    @pytest.mark.unrecognised_patronus_status
    def test_unhashable_raw_value_is_unknown(self, caplog):
        caplog.set_level(logging.DEBUG, logger="space.models")
        assert enums.RunStatus(["not", "hashable"]) is enums.RunStatus.UNKNOWN
        assert enums.RunStatus(["not", "hashable"]) is enums.RunStatus.UNKNOWN
        assert len([r for r in caplog.records if "unrecognised Patronus" in r.getMessage()]) == 1


class TestStatusLevelChecks:

    @pytest.mark.parametrize(
        "cls_name, wrong",
        [
            ("PatronusRun", "CheckStatus"),
            ("PatronusRun", "str"),
            ("PatronusCheckRun", "RunStatus"),
            ("PatronusCheckRun", "str"),
            ("PatronusCheckRunAttempt", "CheckStatus"),
            ("PatronusCheckRunAttempt", "str"),
            ("AttemptDetails", "RunStatus"),
            ("AttemptDetails", "str"),
        ],
    )
    def test_mislevelled_status_raises_type_error(self, cls_name, wrong):
        wrong_status = "SUCCESS" if wrong == "str" else getattr(enums, wrong).SUCCESS
        if cls_name == "PatronusRun":
            build = lambda: make_run(status=wrong_status)
        elif cls_name == "PatronusCheckRun":
            build = lambda: make_check_run(status=wrong_status)
        else:
            cls = {"PatronusCheckRunAttempt": PatronusCheckRunAttempt, "AttemptDetails": AttemptDetails}[cls_name]
            build = lambda: cls(id="a", number=0, status=wrong_status)
        with pytest.raises(TypeError, match="status"):
            build()

    def test_matching_levels_construct(self):
        make_run(status=enums.RunStatus.CANCELING)
        make_check_run(status=enums.CheckStatus.QUEUED)
        PatronusCheckRunAttempt(id="a", number=0, status=enums.AttemptStatus.CANCELED)
        AttemptDetails(id="a", number=0, status=enums.AttemptStatus.CANCELED)


class TestRunMetadataWireValues:
    """`pushMode` and `type` parse to the members Patronus's PushModeDto and RobotTypeDto send."""

    @pytest.mark.parametrize("wire", ["DRY_RUN", "REBASE", "REBASE_AUTOSQUASH", "SQUASH_ALL", "MERGE"])
    async def test_push_mode_wire_values_are_recognised(self, wire, test_accounts):
        run = await PatronusRun.from_api(wire_run("SUCCESS", pushMode=wire), None)
        assert run.push_mode.value == wire

    @pytest.mark.parametrize(
        "wire",
        [
            "WEB_UI",
            "SAFE_PUSH",
            "SPACE_REVIEW_CHERRY_PICK",
            "PATRONUS_CHERRY_PICK",
            "SPACE_SAFE_MERGE",
            "CUSTOM",
            "GITHUB_PR",
        ],
    )
    async def test_run_type_wire_values_are_recognised(self, wire, test_accounts):
        run = await PatronusRun.from_api(wire_run("SUCCESS", type=wire), None)
        assert run.run_type.value == wire
