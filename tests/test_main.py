import pytest
from unittest.mock import patch, MagicMock, AsyncMock

import space.clients as clients_module
import space.mcp.server as server_module
from space.context import AuthenticationError
from space.patronus import PatronusClient


class TestGetClient:
    """Tests for get_client function."""

    def setup_method(self):
        """Reset global client before each test."""
        clients_module._client = None

    def test_get_client_with_token(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        client = clients_module.get_client()

        assert client is not None
        assert client.token == "test-token"

    @patch("space.context._keyring_get", return_value=None)
    @patch("space.context.load_stored_token", return_value=None)
    def test_get_client_missing_token(self, mock_stored, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)

        with pytest.raises(AuthenticationError) as exc_info:
            clients_module.get_client()

        assert "Authentication required" in str(exc_info.value)

    def test_get_client_singleton(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        client1 = clients_module.get_client()
        client2 = clients_module.get_client()

        assert client1 is client2

    def test_get_client_base_url(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        client = clients_module.get_client()
        assert client.base_url == "https://jetbrains.team"


class TestMCPToolsAuthError:
    """Tests that MCP tools return a helpful message when not authenticated."""

    def setup_method(self):
        clients_module._client = None
        clients_module._patronus_client = None

    @patch("space.context._keyring_get", return_value=None)
    @patch("space.context.load_stored_token", return_value=None)
    async def test_space_tool_returns_auth_message(self, mock_stored, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        result = await server_module.get_merge_request("ij", "ultimate", "123")
        assert "Authentication required" in result
        assert "SPACE_TOKEN" in result
        assert "space auth login" in result

    @patch("space.context._keyring_get", return_value=None)
    @patch("space.context.load_stored_token", return_value=None)
    async def test_patronus_tool_returns_auth_message(self, mock_stored, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        result = await server_module.get_patronus_robots("ultimate", "feature/test")
        assert "Authentication required" in result


class TestMCPTools:
    """Tests for MCP tool handler functions — verify they return markdown."""

    def setup_method(self):
        clients_module._client = None

    async def test_get_merge_request_tool(self, monkeypatch, sample_merge_request):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.get_merge_request = AsyncMock(return_value=sample_merge_request)

        with patch.object(server_module, "get_client", return_value=mock_client):
            result = await server_module.get_merge_request("ij", "ultimate", "123456")

        assert "# [MR 188120] Fix authentication bug" in result
        assert "**State:** Opened" in result
        mock_client.get_merge_request.assert_called_once_with("ij", "ultimate", "123456")

    async def test_get_merge_request_discussions_tool(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_discussions = [
            {
                "type": "code_discussion", "id": "disc-1",
                "file": "/src/auth.py", "line": 42, "resolved": False,
                "comments": [
                    {"text": "Please add tests", "author": {"name": "John Doe"}, "created": 1768512553167},
                    {"text": "Done", "author": {"name": "Anna Zhukova"}, "created": 1768512600000},
                ],
            },
            {
                "type": "message", "text": "Someone started dry run",
                "author": {"name": "Anna Zhukova"}, "created": 1768512700000,
            },
        ]

        mock_client = MagicMock()
        mock_client.get_merge_request_discussions = AsyncMock(return_value=mock_discussions)

        with patch.object(server_module, "get_client", return_value=mock_client):
            result = await server_module.get_merge_request_discussions("ij", "ultimate", "123456")

        assert "`/src/auth.py:42`" in result
        assert "Please add tests" in result
        assert "Someone started dry run" in result

    async def test_list_merge_requests_tool(self, monkeypatch, sample_merge_request_list):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.list_merge_requests = AsyncMock(return_value=[item["review"] for item in sample_merge_request_list["data"]])

        with patch.object(server_module, "get_client", return_value=mock_client):
            result = await server_module.list_merge_requests("ij", "ultimate")

        assert "| Title |" in result
        assert "Fix authentication bug" in result

    async def test_list_merge_requests_tool_with_filters(self, monkeypatch, sample_merge_request_list):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.list_merge_requests = AsyncMock(return_value=[item["review"] for item in sample_merge_request_list["data"]])

        with patch.object(server_module, "get_client", return_value=mock_client):
            await server_module.list_merge_requests("ij", "ultimate", branch="feature", state="Open", limit=10)

        mock_client.list_merge_requests.assert_called_once_with(
            project="ij", repository="ultimate", branch="feature", state="Open", limit=10,
        )

    async def test_list_merge_requests_tool_default_limit(self, monkeypatch, sample_merge_request_list):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.list_merge_requests = AsyncMock(return_value=[item["review"] for item in sample_merge_request_list["data"]])

        with patch.object(server_module, "get_client", return_value=mock_client):
            await server_module.list_merge_requests("ij", "ultimate")

        call_kwargs = mock_client.list_merge_requests.call_args.kwargs
        assert call_kwargs["limit"] == 20

    async def test_find_merge_request_by_branch_tool(self, monkeypatch, sample_merge_request):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.find_merge_request_by_branch = AsyncMock(return_value=sample_merge_request)

        with patch.object(server_module, "get_client", return_value=mock_client):
            result = await server_module.find_merge_request_by_branch("ij", "ultimate", "azhukova/fix-auth")

        assert "# [MR 188120]" in result
        mock_client.find_merge_request_by_branch.assert_called_once_with(
            "ij", "ultimate", "azhukova/fix-auth", state=None
        )

    async def test_find_merge_request_by_branch_tool_with_state(self, monkeypatch, sample_merge_request):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.find_merge_request_by_branch = AsyncMock(return_value=sample_merge_request)

        with patch.object(server_module, "get_client", return_value=mock_client):
            await server_module.find_merge_request_by_branch("ij", "ultimate", "azhukova/fix-auth", state="Closed")

        mock_client.find_merge_request_by_branch.assert_called_once_with(
            "ij", "ultimate", "azhukova/fix-auth", state="Closed"
        )

    async def test_find_merge_request_by_branch_tool_not_found(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.find_merge_request_by_branch = AsyncMock(return_value=None)

        with patch.object(server_module, "get_client", return_value=mock_client):
            result = await server_module.find_merge_request_by_branch("ij", "ultimate", "nonexistent")

        assert result == "No merge request found."


class TestGetPatronusClient:
    """Tests for get_patronus_client function."""

    def setup_method(self):
        clients_module._patronus_client = None

    def test_get_patronus_client_with_token(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        client = clients_module.get_patronus_client()
        assert client is not None
        assert client.token == "test-token"

    @patch("space.context._keyring_get", return_value=None)
    @patch("space.context.load_stored_token", return_value=None)
    def test_get_patronus_client_missing_token(self, mock_stored, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        with pytest.raises(AuthenticationError) as exc_info:
            clients_module.get_patronus_client()
        assert "Authentication required" in str(exc_info.value)

    def test_get_patronus_client_singleton(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        client1 = clients_module.get_patronus_client()
        client2 = clients_module.get_patronus_client()
        assert client1 is client2

    def test_get_patronus_client_base_url(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        client = clients_module.get_patronus_client()
        assert client.base_url == "https://patronus.labs.jb.gg"


class TestPatronusMCPTools:
    """Tests for Patronus MCP tool handler functions — verify they return markdown."""

    def setup_method(self):
        clients_module._patronus_client = None

    async def test_get_patronus_robots_tool(self, monkeypatch, sample_robot_overview):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.list_robots = AsyncMock(return_value=[sample_robot_overview])

        with patch.object(server_module, "get_patronus_client", return_value=mock_client):
            result = await server_module.get_patronus_robots("ultimate", "feature/test")

        assert "SUCCESSFUL" in result
        assert "cc448634-880e-411f-9ee6-347e9a6087ac" in result
        mock_client.list_robots.assert_called_once_with(
            repository="ultimate", source_branch="feature/test", target_branch=None,
        )

    async def test_get_patronus_robots_tool_with_target(self, monkeypatch, sample_robot_overview):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.list_robots = AsyncMock(return_value=[sample_robot_overview])

        with patch.object(server_module, "get_patronus_client", return_value=mock_client):
            await server_module.get_patronus_robots("ultimate", "feature/test", target_branch="master")

        mock_client.list_robots.assert_called_once_with(
            repository="ultimate", source_branch="feature/test", target_branch="master",
        )

    async def test_get_patronus_robots_tool_empty(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.list_robots = AsyncMock(return_value=[])

        with patch.object(server_module, "get_patronus_client", return_value=mock_client):
            result = await server_module.get_patronus_robots("ultimate", "feature/test")

        assert result == "No Patronus robots found."

    async def test_get_patronus_robot_details_tool(self, monkeypatch, sample_robot_overview, sample_teamcity_checks, sample_robot_problems, sample_attempt_details):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.get_robot = AsyncMock(return_value=sample_robot_overview)
        mock_client.get_robot_teamcity_checks = AsyncMock(return_value=sample_teamcity_checks)
        mock_client.get_robot_problems = AsyncMock(return_value=sample_robot_problems)
        mock_client.get_attempt_details = AsyncMock(return_value=sample_attempt_details)

        with patch.object(server_module, "get_patronus_client", return_value=mock_client):
            result = await server_module.get_patronus_robot_details("cc448634-880e-411f-9ee6-347e9a6087ac")

        assert "# Fix auth (dry run)" in result
        assert "**Status:** SUCCESSFUL" in result
        assert "Compile All" in result
        assert "3 tests failed in Unit Tests" in result
        # Attempt details for the failed "Unit Tests" check
        assert "## Failed Checks" in result
        assert "com.example.FooTest.test something important" in result
        mock_client.get_attempt_details.assert_called_once_with("attempt-fail-1")

    async def test_get_patronus_robot_details_no_failures(self, monkeypatch, sample_robot_overview, sample_robot_problems):
        """No attempt details fetched when all checks succeed."""
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        success_checks = [
            {"name": "Compile All", "status": "SUCCESS", "attempts": [{"id": "a1", "status": "SUCCESS"}]},
        ]

        mock_client = MagicMock()
        mock_client.get_robot = AsyncMock(return_value=sample_robot_overview)
        mock_client.get_robot_teamcity_checks = AsyncMock(return_value=success_checks)
        mock_client.get_robot_problems = AsyncMock(return_value=sample_robot_problems)

        with patch.object(server_module, "get_patronus_client", return_value=mock_client):
            result = await server_module.get_patronus_robot_details("cc448634-880e-411f-9ee6-347e9a6087ac")

        assert "## Failed Checks" not in result
        mock_client.get_attempt_details.assert_not_called()

    async def test_start_patronus_dry_run_tool(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.start_safe_merge = AsyncMock(return_value={"jobId": "job-123"})

        with patch.object(server_module, "get_client", return_value=mock_client):
            result = await server_module.start_patronus_dry_run("ij", "194108")

        assert "Dry run started" in result
        mock_client.start_safe_merge.assert_called_once_with(
            "ij", "194108", operation="DryRun",
        )

    async def test_cancel_patronus_robot_tool(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.cancel_robot = AsyncMock(return_value=None)

        with patch.object(server_module, "get_patronus_client", return_value=mock_client):
            result = await server_module.cancel_patronus_robot("2d211ced-1976-4586-b4fe-dcf3ef285c34")

        assert "2d211ced-1976-4586-b4fe-dcf3ef285c34" in result
        assert "Cancellation" in result
        mock_client.cancel_robot.assert_called_once_with("2d211ced-1976-4586-b4fe-dcf3ef285c34")
