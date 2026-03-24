import pytest
import httpx

from space.patronus import PatronusClient


class TestPatronusClientInit:
    """Tests for PatronusClient constructor."""

    def test_init(self):
        client = PatronusClient(token="test-token")
        assert client.base_url == "https://patronus.labs.jb.gg"
        assert client.token == "test-token"


class TestPatronusClientHeaders:
    """Tests for _headers method."""

    def test_headers_contains_bearer_token(self, patronus_client):
        headers = patronus_client._headers()
        assert headers["Authorization"] == "Bearer test-token"

    def test_headers_contains_accept_json(self, patronus_client):
        headers = patronus_client._headers()
        assert headers["Accept"] == "application/json"


class TestListRobots:
    """Tests for list_robots method."""

    async def test_list_robots_success(self, httpx_mock, patronus_client, sample_robots_list):
        httpx_mock.add_response(json=sample_robots_list)

        result = await patronus_client.list_robots("ultimate")

        assert len(result) == 1
        assert result[0]["id"] == "cc448634-880e-411f-9ee6-347e9a6087ac"
        assert result[0]["status"] == "SUCCESSFUL"

    async def test_list_robots_url_format(self, httpx_mock, patronus_client, sample_robots_list):
        httpx_mock.add_response(json=sample_robots_list)

        await patronus_client.list_robots("ultimate")

        request = httpx_mock.get_request()
        assert "/app/rest/v1/robots" in str(request.url)
        assert "repository=ultimate" in str(request.url)

    async def test_list_robots_with_source_branch(self, httpx_mock, patronus_client, sample_robots_list):
        httpx_mock.add_response(json=sample_robots_list)

        await patronus_client.list_robots("ultimate", source_branch="feature/test")

        request = httpx_mock.get_request()
        assert "sourceBranch=feature" in str(request.url)

    async def test_list_robots_with_target_branch(self, httpx_mock, patronus_client, sample_robots_list):
        httpx_mock.add_response(json=sample_robots_list)

        await patronus_client.list_robots("ultimate", target_branch="master")

        request = httpx_mock.get_request()
        assert "targetBranch=master" in str(request.url)

    async def test_list_robots_empty(self, httpx_mock, patronus_client):
        httpx_mock.add_response(json={"me": None, "robots": [], "start": "", "end": ""})

        result = await patronus_client.list_robots("ultimate")

        assert result == []

    async def test_list_robots_unauthorized(self, httpx_mock, patronus_client):
        httpx_mock.add_response(status_code=403)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await patronus_client.list_robots("ultimate")

        assert exc_info.value.response.status_code == 403

    async def test_list_robots_without_repository(self, httpx_mock, patronus_client, sample_robots_list):
        """repository=None omits the parameter from the query."""
        httpx_mock.add_response(json=sample_robots_list)

        result = await patronus_client.list_robots(source_branch="feature/x")

        request = httpx_mock.get_request()
        assert "repository=" not in str(request.url)
        assert "sourceBranch=feature" in str(request.url)
        assert len(result) == 1

    async def test_list_robots_network_error(self, httpx_mock, patronus_client):
        httpx_mock.add_exception(httpx.ConnectError("Connection failed"))

        with pytest.raises(httpx.ConnectError):
            await patronus_client.list_robots("ultimate")


class TestGetRobot:
    """Tests for get_robot method."""

    async def test_get_robot_success(self, httpx_mock, patronus_client, sample_robot_overview):
        httpx_mock.add_response(json=sample_robot_overview)

        result = await patronus_client.get_robot("cc448634-880e-411f-9ee6-347e9a6087ac")

        assert result["id"] == "cc448634-880e-411f-9ee6-347e9a6087ac"
        assert result["status"] == "SUCCESSFUL"
        assert result["pushMode"] == "DRY_RUN"

    async def test_get_robot_url_format(self, httpx_mock, patronus_client, sample_robot_overview):
        httpx_mock.add_response(json=sample_robot_overview)

        await patronus_client.get_robot("cc448634-880e-411f-9ee6-347e9a6087ac")

        request = httpx_mock.get_request()
        assert "/app/rest/v1/robots/cc448634-880e-411f-9ee6-347e9a6087ac" in str(request.url)

    async def test_get_robot_not_found(self, httpx_mock, patronus_client):
        httpx_mock.add_response(status_code=404)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await patronus_client.get_robot("nonexistent")

        assert exc_info.value.response.status_code == 404

    async def test_get_robot_server_error(self, httpx_mock, patronus_client):
        httpx_mock.add_response(status_code=500)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await patronus_client.get_robot("some-id")

        assert exc_info.value.response.status_code == 500


class TestGetRobotTeamcityChecks:
    """Tests for get_robot_teamcity_checks method."""

    async def test_get_teamcity_checks_success(self, httpx_mock, patronus_client, sample_teamcity_checks_response):
        httpx_mock.add_response(json=sample_teamcity_checks_response)

        result = await patronus_client.get_robot_teamcity_checks("cc448634-880e-411f-9ee6-347e9a6087ac")

        assert len(result) == 2
        assert result[0]["name"] == "Compile All"
        assert result[0]["status"] == "SUCCESS"
        assert result[1]["name"] == "Unit Tests"
        assert result[1]["status"] == "FAILURE"

    async def test_get_teamcity_checks_url_format(self, httpx_mock, patronus_client, sample_teamcity_checks_response):
        httpx_mock.add_response(json=sample_teamcity_checks_response)

        await patronus_client.get_robot_teamcity_checks("some-robot-id")

        request = httpx_mock.get_request()
        assert "/app/rest/v1/robots/some-robot-id/teamcity-checks" in str(request.url)

    async def test_get_teamcity_checks_empty(self, httpx_mock, patronus_client):
        httpx_mock.add_response(json={"robotId": "some-id", "teamCityChecks": []})

        result = await patronus_client.get_robot_teamcity_checks("some-robot-id")

        assert result == []

    async def test_get_teamcity_checks_unauthorized(self, httpx_mock, patronus_client):
        httpx_mock.add_response(status_code=403)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await patronus_client.get_robot_teamcity_checks("some-robot-id")

        assert exc_info.value.response.status_code == 403


class TestGetRobotProblems:
    """Tests for get_robot_problems method."""

    async def test_get_problems_success(self, httpx_mock, patronus_client, sample_robot_problems):
        httpx_mock.add_response(json=sample_robot_problems)

        result = await patronus_client.get_robot_problems("cc448634-880e-411f-9ee6-347e9a6087ac")

        assert result["robotId"] == "cc448634-880e-411f-9ee6-347e9a6087ac"
        assert len(result["problems"]) == 1
        assert result["problems"][0]["title"] == "3 tests failed in Unit Tests"

    async def test_get_problems_url_format(self, httpx_mock, patronus_client, sample_robot_problems):
        httpx_mock.add_response(json=sample_robot_problems)

        await patronus_client.get_robot_problems("some-robot-id")

        request = httpx_mock.get_request()
        assert "/app/rest/v1/robots/some-robot-id/problems" in str(request.url)

    async def test_get_problems_empty(self, httpx_mock, patronus_client):
        httpx_mock.add_response(json={"robotId": "some-id", "problems": []})

        result = await patronus_client.get_robot_problems("some-id")

        assert result["problems"] == []

    async def test_get_problems_unauthorized(self, httpx_mock, patronus_client):
        httpx_mock.add_response(status_code=403)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await patronus_client.get_robot_problems("some-robot-id")

        assert exc_info.value.response.status_code == 403


class TestGetAttemptDetails:
    """Tests for get_attempt_details method."""

    async def test_get_attempt_details_success(self, httpx_mock, patronus_client, sample_attempt_details):
        httpx_mock.add_response(json=sample_attempt_details)

        result = await patronus_client.get_attempt_details("attempt-fail-1")

        assert result["id"] == "attempt-fail-1"
        assert result["status"] == "FAILURE"
        assert result["failedTestsNumber"] == 1
        assert len(result["failedTests"]) == 1
        assert "FooTest" in result["failedTests"][0]["name"]

    async def test_get_attempt_details_url_format(self, httpx_mock, patronus_client, sample_attempt_details):
        httpx_mock.add_response(json=sample_attempt_details)

        await patronus_client.get_attempt_details("some-attempt-id")

        request = httpx_mock.get_request()
        assert "/app/rest/v1/teamcity-checks/attempts/some-attempt-id" in str(request.url)

    async def test_get_attempt_details_not_found(self, httpx_mock, patronus_client):
        httpx_mock.add_response(status_code=404)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await patronus_client.get_attempt_details("nonexistent")

        assert exc_info.value.response.status_code == 404


class TestCancelRobot:
    """Tests for cancel_robot method."""

    async def test_cancel_robot_success(self, httpx_mock, patronus_client):
        httpx_mock.add_response(status_code=200)

        await patronus_client.cancel_robot("2d211ced-1976-4586-b4fe-dcf3ef285c34")

        request = httpx_mock.get_request()
        assert request.method == "PUT"
        assert "/app/rest/v1/robots/2d211ced-1976-4586-b4fe-dcf3ef285c34/cancel" in str(request.url)

    async def test_cancel_robot_not_found(self, httpx_mock, patronus_client):
        httpx_mock.add_response(status_code=404)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await patronus_client.cancel_robot("nonexistent")

        assert exc_info.value.response.status_code == 404


class TestExtractRobotIds:
    """Tests for extract_robot_ids function."""

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
        assert result == [
            "aaaa1111-2222-3333-4444-555566667777",
            "bbbb1111-2222-3333-4444-555566667777",
        ]

    def test_no_urls(self):
        from space.patronus import extract_robot_ids
        assert extract_robot_ids("No robot URLs here") == []

    def test_bare_text_no_match(self):
        from space.patronus import extract_robot_ids
        assert extract_robot_ids("") == []

    def test_deduplicates(self):
        from space.patronus import extract_robot_ids
        url = "https://patronus.labs.jb.gg/robot/917ff740-e579-409a-b4a2-3014ba96529b"
        text = f"Started: {url}\nFinished: {url}"
        assert extract_robot_ids(text) == ["917ff740-e579-409a-b4a2-3014ba96529b"]


class TestListRobotsForReview:
    """Tests for list_robots_for_review method."""

    async def test_filters_by_review_url(self, httpx_mock, patronus_client):
        """Only robots whose spaceReviewUrl matches the project/review are returned."""
        httpx_mock.add_response(json={"robots": [
            {"id": "1", "spaceReviewUrl": "https://jetbrains.team/p/SPACE-MCP/reviews/86/timeline"},
            {"id": "2", "spaceReviewUrl": "https://jetbrains.team/p/IJ/reviews/1000/timeline"},
            {"id": "3", "spaceReviewUrl": "https://jetbrains.team/p/SPACE-MCP/reviews/99/timeline"},
        ]})

        result = await patronus_client.list_robots_for_review(
            "space-mcp", "86", source_branch="test/abc",
        )
        assert len(result) == 1
        assert result[0]["id"] == "1"

    async def test_case_insensitive_project(self, httpx_mock, patronus_client):
        """Project key matching is case-insensitive."""
        httpx_mock.add_response(json={"robots": [
            {"id": "1", "spaceReviewUrl": "https://jetbrains.team/p/SPACE-MCP/reviews/86/timeline"},
        ]})

        result = await patronus_client.list_robots_for_review(
            "space-mcp", "86", source_branch="test/abc",
        )
        assert len(result) == 1

    async def test_skips_none_review_url(self, httpx_mock, patronus_client):
        """Robots with spaceReviewUrl=None are filtered out."""
        httpx_mock.add_response(json={"robots": [
            {"id": "1", "spaceReviewUrl": None},
            {"id": "2", "spaceReviewUrl": "https://jetbrains.team/p/SPACE-MCP/reviews/86/timeline"},
        ]})

        result = await patronus_client.list_robots_for_review(
            "space-mcp", "86", source_branch="test/abc",
        )
        assert len(result) == 1
        assert result[0]["id"] == "2"

    async def test_empty_robots(self, httpx_mock, patronus_client):
        httpx_mock.add_response(json={"robots": []})

        result = await patronus_client.list_robots_for_review(
            "space-mcp", "86", source_branch="test/abc",
        )
        assert result == []

    async def test_passes_branch_params(self, httpx_mock, patronus_client):
        """sourceBranch and targetBranch are passed as query params, no repository."""
        httpx_mock.add_response(json={"robots": []})

        await patronus_client.list_robots_for_review(
            "space-mcp", "86", source_branch="feature/x", target_branch="main",
        )

        request = httpx_mock.get_request()
        url = str(request.url)
        assert "sourceBranch=feature" in url
        assert "targetBranch=main" in url
        assert "repository=" not in url

    async def test_requires_at_least_one_branch(self, patronus_client):
        """ValueError if neither source_branch nor target_branch provided."""
        with pytest.raises(ValueError):
            await patronus_client.list_robots_for_review("space-mcp", "86")

    async def test_review_number_as_int(self, httpx_mock, patronus_client):
        """review_number can be an int."""
        httpx_mock.add_response(json={"robots": [
            {"id": "1", "spaceReviewUrl": "https://jetbrains.team/p/IJ/reviews/42/timeline"},
        ]})

        result = await patronus_client.list_robots_for_review(
            "ij", 42, source_branch="test/abc",
        )
        assert len(result) == 1


class TestGetMe:
    """Tests for get_me method."""

    async def test_get_me_success(self, httpx_mock, patronus_client, sample_robots_list):
        httpx_mock.add_response(json=sample_robots_list)

        result = await patronus_client.get_me("ultimate")

        assert result["type"] == "USER"
        assert result["name"] == "Anna Zhukova"

    async def test_get_me_url_format(self, httpx_mock, patronus_client, sample_robots_list):
        httpx_mock.add_response(json=sample_robots_list)

        await patronus_client.get_me("ultimate")

        request = httpx_mock.get_request()
        assert "/app/rest/v1/robots" in str(request.url)
        assert "repository=ultimate" in str(request.url)
