"""Tests for Patronus domain model dataclasses."""

from datetime import datetime, timezone

from space.models import FailedBuild, FailedTest, PatronusCheckConfig, PatronusCheckRunAttempt
from space.models.enums import RunStatus


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
