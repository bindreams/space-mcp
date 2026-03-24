from __future__ import annotations

import pytest
import httpx

from space.models import (
    AttemptDetails,
    PatronusCheckRun,
    PatronusRun,
    RunStatus,
)
from space.patronus import PatronusClient


def _robot_dict(id: str = "robot-1", space_review_url: str | None = None, **overrides) -> dict:
    """Build a minimal-but-valid robot overview dict for tests."""
    base = {
        "id": id,
        "name": "Test Robot",
        "status": "SUCCESSFUL",
        "pushMode": "DRY_RUN",
        "type": "SAFE_PUSH",
        "sourceBranch": "refs/patronus/safepush/abc",
        "targetBranch": "master",
        "repository": "ultimate",
        "startDateTime": "2026-01-15T08:00:02Z",
        "finishDateTime": "2026-01-15T08:08:08Z",
        "cancellationReason": None,
        "owner": {"type": "USER", "id": "user-azhukova", "name": "Anna Zhukova", "email": "anna@test.com"},
        "spaceReviewUrl": space_review_url,
        "spaceReviewKey": None,
        "options": {},
    }
    base.update(overrides)
    return base


class TestPatronusClientInit:

    def test_init(self):
        client = PatronusClient(token="test-token")
        assert client.base_url == "https://patronus.labs.jb.gg"
        assert client.token == "test-token"


class TestPatronusClientHeaders:

    def test_headers_contains_bearer_token(self, patronus_client):
        headers = patronus_client._headers()
        assert headers["Authorization"] == "Bearer test-token"


class TestListRobots:

    async def test_list_robots_returns_models(self, httpx_mock, patronus_client, sample_robots_list, test_accounts):
        httpx_mock.add_response(json=sample_robots_list)

        result = await patronus_client.list_robots("ultimate")

        assert len(result) == 1
        assert isinstance(result[0], PatronusRun)
        assert result[0].id == "cc448634-880e-411f-9ee6-347e9a6087ac"
        assert result[0].status == RunStatus.SUCCESSFUL

    async def test_list_robots_url_format(self, httpx_mock, patronus_client, sample_robots_list, test_accounts):
        httpx_mock.add_response(json=sample_robots_list)

        await patronus_client.list_robots("ultimate")

        request = httpx_mock.get_request()
        assert "/app/rest/v1/robots" in str(request.url)
        assert "repository=ultimate" in str(request.url)

    async def test_list_robots_empty(self, httpx_mock, patronus_client, test_accounts):
        httpx_mock.add_response(json={"me": None, "robots": [], "start": "", "end": ""})

        result = await patronus_client.list_robots("ultimate")

        assert result == []

    async def test_list_robots_unauthorized(self, httpx_mock, patronus_client):
        httpx_mock.add_response(status_code=403)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await patronus_client.list_robots("ultimate")

        assert exc_info.value.response.status_code == 403


class TestGetRobot:

    async def test_get_robot_returns_model(self, httpx_mock, patronus_client, sample_robot_overview, test_accounts):
        httpx_mock.add_response(json=sample_robot_overview)

        result = await patronus_client.get_robot("cc448634-880e-411f-9ee6-347e9a6087ac")

        assert isinstance(result, PatronusRun)
        assert result.id == "cc448634-880e-411f-9ee6-347e9a6087ac"
        assert result.status == RunStatus.SUCCESSFUL
        assert result.push_mode.value == "DRY_RUN"
        assert result.owner.username == "azhukova"

    async def test_get_robot_not_found(self, httpx_mock, patronus_client):
        httpx_mock.add_response(status_code=404)

        with pytest.raises(httpx.HTTPStatusError):
            await patronus_client.get_robot("nonexistent")


class TestGetRobotTeamcityChecks:

    async def test_get_teamcity_checks_returns_models(self, httpx_mock, patronus_client, sample_teamcity_checks_response):
        httpx_mock.add_response(json=sample_teamcity_checks_response)

        result = await patronus_client.get_robot_teamcity_checks("cc448634-880e-411f-9ee6-347e9a6087ac")

        assert len(result) == 2
        assert isinstance(result[0], PatronusCheckRun)
        assert result[0].config.name == "Compile All"
        assert result[0].status == RunStatus.SUCCESS
        assert result[1].config.name == "Unit Tests"
        assert result[1].status == RunStatus.FAILURE

    async def test_get_teamcity_checks_empty(self, httpx_mock, patronus_client):
        httpx_mock.add_response(json={"robotId": "some-id", "teamCityChecks": []})

        result = await patronus_client.get_robot_teamcity_checks("some-robot-id")

        assert result == []


class TestGetRobotProblems:

    async def test_get_problems_returns_tuple(self, httpx_mock, patronus_client, sample_robot_problems):
        httpx_mock.add_response(json=sample_robot_problems)

        result = await patronus_client.get_robot_problems("cc448634-880e-411f-9ee6-347e9a6087ac")

        assert len(result) == 1
        assert result[0].title == "3 tests failed in Unit Tests"
        assert result[0].details == "Failures in `com.example.FooTest`"

    async def test_get_problems_empty(self, httpx_mock, patronus_client):
        httpx_mock.add_response(json={"robotId": "some-id", "problems": []})

        result = await patronus_client.get_robot_problems("some-id")

        assert result == ()


class TestGetAttemptDetails:

    async def test_get_attempt_details_returns_model(self, httpx_mock, patronus_client, sample_attempt_details):
        httpx_mock.add_response(json=sample_attempt_details)

        result = await patronus_client.get_attempt_details("attempt-fail-1")

        assert isinstance(result, AttemptDetails)
        assert result.id == "attempt-fail-1"
        assert result.status == RunStatus.FAILURE
        assert len(result.failed_tests) == 1
        assert "FooTest" in result.failed_tests[0].name
        assert len(result.failed_builds) == 1

    async def test_get_attempt_details_not_found(self, httpx_mock, patronus_client):
        httpx_mock.add_response(status_code=404)

        with pytest.raises(httpx.HTTPStatusError):
            await patronus_client.get_attempt_details("nonexistent")


class TestCancelRobot:

    async def test_cancel_robot_success(self, httpx_mock, patronus_client):
        httpx_mock.add_response(status_code=200)

        await patronus_client.cancel_robot("2d211ced-1976-4586-b4fe-dcf3ef285c34")

        request = httpx_mock.get_request()
        assert request.method == "PUT"

    async def test_cancel_robot_not_found(self, httpx_mock, patronus_client):
        httpx_mock.add_response(status_code=404)

        with pytest.raises(httpx.HTTPStatusError):
            await patronus_client.cancel_robot("nonexistent")


class TestExtractRobotIds:

    def test_single_url(self):
        from space.patronus import extract_robot_ids
        text = "https://patronus.labs.jb.gg/robot/917ff740-e579-409a-b4a2-3014ba96529b"
        assert extract_robot_ids(text) == ["917ff740-e579-409a-b4a2-3014ba96529b"]

    def test_multiple_urls(self):
        from space.patronus import extract_robot_ids
        text = (
            "Started: https://patronus.labs.jb.gg/robot/aaaa1111-2222-3333-4444-555566667777\n"
            "Success: https://patronus-staging.labs.jb.gg/robot/bbbb1111-2222-3333-4444-555566667777"
        )
        result = extract_robot_ids(text)
        assert len(result) == 2

    def test_no_urls(self):
        from space.patronus import extract_robot_ids
        assert extract_robot_ids("No robot URLs here") == []

    def test_deduplicates(self):
        from space.patronus import extract_robot_ids
        url = "https://patronus.labs.jb.gg/robot/917ff740-e579-409a-b4a2-3014ba96529b"
        assert len(extract_robot_ids(f"{url}\n{url}")) == 1


class TestListRobotsForReview:

    async def test_filters_by_review_url(self, httpx_mock, patronus_client, test_accounts):
        httpx_mock.add_response(json={"robots": [
            _robot_dict("1", "https://jetbrains.team/p/SPACE-MCP/reviews/86/timeline"),
            _robot_dict("2", "https://jetbrains.team/p/IJ/reviews/1000/timeline"),
            _robot_dict("3", "https://jetbrains.team/p/SPACE-MCP/reviews/99/timeline"),
        ]})

        result = await patronus_client.list_robots_for_review(
            "space-mcp", "86", source_branch="test/abc",
        )
        assert len(result) == 1
        assert result[0].id == "1"

    async def test_case_insensitive_project(self, httpx_mock, patronus_client, test_accounts):
        httpx_mock.add_response(json={"robots": [
            _robot_dict("1", "https://jetbrains.team/p/SPACE-MCP/reviews/86/timeline"),
        ]})

        result = await patronus_client.list_robots_for_review(
            "space-mcp", "86", source_branch="test/abc",
        )
        assert len(result) == 1

    async def test_empty_robots(self, httpx_mock, patronus_client, test_accounts):
        httpx_mock.add_response(json={"robots": []})

        result = await patronus_client.list_robots_for_review(
            "space-mcp", "86", source_branch="test/abc",
        )
        assert result == []

    async def test_requires_at_least_one_branch(self, patronus_client):
        with pytest.raises(ValueError):
            await patronus_client.list_robots_for_review("space-mcp", "86")


class TestGetMe:

    async def test_get_me_returns_dict(self, httpx_mock, patronus_client, sample_robots_list):
        httpx_mock.add_response(json=sample_robots_list)

        result = await patronus_client.get_me("ultimate")

        assert result["type"] == "USER"
        assert result["name"] == "Anna Zhukova"
