import pytest
import httpx

from space.patronus import PatronusClient


class TestPatronusClientInit:
    """Tests for PatronusClient constructor."""

    def test_init_with_defaults(self):
        client = PatronusClient(token="test-token")
        assert client.base_url == "https://patronus.labs.jb.gg"
        assert client.token == "test-token"

    def test_init_with_custom_base_url(self):
        client = PatronusClient(token="test-token", base_url="https://custom-patronus.example.com")
        assert client.base_url == "https://custom-patronus.example.com"

    def test_init_strips_trailing_slash(self):
        client = PatronusClient(token="test-token", base_url="https://example.com/")
        assert client.base_url == "https://example.com"


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
        assert result[1]["status"] == "RUNNING"

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
        assert result["problems"][0]["type"] == "TEST_FAILURE"

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
