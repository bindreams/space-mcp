import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

import space_mcp.__main__ as main_module
from space_mcp.patronus import PatronusClient


class TestGetClient:
    """Tests for get_client function."""

    def setup_method(self):
        """Reset global client before each test."""
        main_module._client = None

    def test_get_client_with_token(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        client = main_module.get_client()

        assert client is not None
        assert client.token == "test-token"

    def test_get_client_missing_token(self, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)

        with pytest.raises(ValueError) as exc_info:
            main_module.get_client()

        assert "SPACE_TOKEN" in str(exc_info.value)

    def test_get_client_singleton(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        client1 = main_module.get_client()
        client2 = main_module.get_client()

        assert client1 is client2

    def test_get_client_uses_default_base_url(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        client = main_module.get_client()

        assert client.base_url == "https://jetbrains.team"


class TestMCPTools:
    """Tests for MCP tool handler functions."""

    def setup_method(self):
        """Reset global client before each test."""
        main_module._client = None

    async def test_get_merge_request_tool(self, monkeypatch, sample_merge_request):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.get_merge_request = AsyncMock(return_value=sample_merge_request)

        with patch.object(main_module, "get_client", return_value=mock_client):
            result = await main_module.get_merge_request("ij", "ultimate", "123456")

        parsed = json.loads(result)
        assert parsed["id"] == "123456"
        mock_client.get_merge_request.assert_called_once_with("ij", "ultimate", "123456")

    async def test_get_merge_request_tool_returns_formatted_json(self, monkeypatch, sample_merge_request):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.get_merge_request = AsyncMock(return_value=sample_merge_request)

        with patch.object(main_module, "get_client", return_value=mock_client):
            result = await main_module.get_merge_request("ij", "ultimate", "123456")

        # Should be pretty-printed JSON with indentation
        assert "\n" in result
        assert "  " in result

    async def test_get_merge_request_discussions_tool(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        # The client returns a mixed list of code discussions and general messages
        mock_discussions = [
            {
                "type": "code_discussion",
                "id": "disc-1",
                "file": "/src/auth.py",
                "line": 42,
                "resolved": False,
                "comments": [
                    {"text": "Please add tests", "author": {"username": "jdoe", "name": "John Doe"}, "created": 123},
                    {"text": "Done", "author": {"username": "azhukova", "name": "Anna Zhukova"}, "created": 456},
                ],
            },
            {
                "type": "message",
                "text": "Someone started dry run",
                "author": {"username": "azhukova", "name": "Anna Zhukova"},
                "created": 789,
            },
        ]

        mock_client = MagicMock()
        mock_client.get_merge_request_discussions = AsyncMock(return_value=mock_discussions)

        with patch.object(main_module, "get_client", return_value=mock_client):
            result = await main_module.get_merge_request_discussions("ij", "ultimate", "123456")

        parsed = json.loads(result)
        assert len(parsed) == 2
        code_discussions = [p for p in parsed if p["type"] == "code_discussion"]
        assert len(code_discussions) == 1
        assert code_discussions[0]["file"] == "/src/auth.py"
        assert len(code_discussions[0]["comments"]) == 2

    async def test_list_merge_requests_tool(self, monkeypatch, sample_merge_request_list):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.list_merge_requests = AsyncMock(return_value=sample_merge_request_list["data"])

        with patch.object(main_module, "get_client", return_value=mock_client):
            result = await main_module.list_merge_requests("ij", "ultimate")

        parsed = json.loads(result)
        assert len(parsed) == 2

    async def test_list_merge_requests_tool_with_filters(self, monkeypatch, sample_merge_request_list):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.list_merge_requests = AsyncMock(return_value=sample_merge_request_list["data"])

        with patch.object(main_module, "get_client", return_value=mock_client):
            await main_module.list_merge_requests("ij", "ultimate", branch="feature", state="Open", limit=10)

        mock_client.list_merge_requests.assert_called_once_with(
            project="ij",
            repository="ultimate",
            branch="feature",
            state="Open",
            limit=10,
        )

    async def test_list_merge_requests_tool_default_limit(self, monkeypatch, sample_merge_request_list):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.list_merge_requests = AsyncMock(return_value=sample_merge_request_list["data"])

        with patch.object(main_module, "get_client", return_value=mock_client):
            await main_module.list_merge_requests("ij", "ultimate")

        # Default limit should be 20
        call_kwargs = mock_client.list_merge_requests.call_args.kwargs
        assert call_kwargs["limit"] == 20

    async def test_find_merge_request_by_branch_tool(self, monkeypatch, sample_merge_request):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.find_merge_request_by_branch = AsyncMock(return_value=sample_merge_request)

        with patch.object(main_module, "get_client", return_value=mock_client):
            result = await main_module.find_merge_request_by_branch("ij", "ultimate", "azhukova/fix-auth")

        parsed = json.loads(result)
        assert parsed["id"] == "123456"
        mock_client.find_merge_request_by_branch.assert_called_once_with(
            "ij", "ultimate", "azhukova/fix-auth", state=None
        )

    async def test_find_merge_request_by_branch_tool_with_state(self, monkeypatch, sample_merge_request):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.find_merge_request_by_branch = AsyncMock(return_value=sample_merge_request)

        with patch.object(main_module, "get_client", return_value=mock_client):
            result = await main_module.find_merge_request_by_branch("ij", "ultimate", "azhukova/fix-auth", state="Closed")

        mock_client.find_merge_request_by_branch.assert_called_once_with(
            "ij", "ultimate", "azhukova/fix-auth", state="Closed"
        )

    async def test_find_merge_request_by_branch_tool_not_found(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.find_merge_request_by_branch = AsyncMock(return_value=None)

        with patch.object(main_module, "get_client", return_value=mock_client):
            result = await main_module.find_merge_request_by_branch("ij", "ultimate", "nonexistent")

        assert result == "null"


class TestGetPatronusClient:
    """Tests for get_patronus_client function."""

    def setup_method(self):
        """Reset global patronus client before each test."""
        main_module._patronus_client = None

    def test_get_patronus_client_with_token(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        client = main_module.get_patronus_client()

        assert client is not None
        assert client.token == "test-token"

    def test_get_patronus_client_missing_token(self, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)

        with pytest.raises(ValueError) as exc_info:
            main_module.get_patronus_client()

        assert "SPACE_TOKEN" in str(exc_info.value)

    def test_get_patronus_client_singleton(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        client1 = main_module.get_patronus_client()
        client2 = main_module.get_patronus_client()

        assert client1 is client2

    def test_get_patronus_client_default_base_url(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        client = main_module.get_patronus_client()

        assert client.base_url == "https://patronus.labs.jb.gg"


class TestPatronusMCPTools:
    """Tests for Patronus MCP tool handler functions."""

    def setup_method(self):
        """Reset global clients before each test."""
        main_module._patronus_client = None

    async def test_get_patronus_robots_tool(self, monkeypatch, sample_robot_overview):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.list_robots = AsyncMock(return_value=[sample_robot_overview])

        with patch.object(main_module, "get_patronus_client", return_value=mock_client):
            result = await main_module.get_patronus_robots("ultimate", "feature/test")

        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["id"] == "cc448634-880e-411f-9ee6-347e9a6087ac"
        assert parsed[0]["status"] == "SUCCESSFUL"
        mock_client.list_robots.assert_called_once_with(
            repository="ultimate",
            source_branch="feature/test",
            target_branch=None,
        )

    async def test_get_patronus_robots_tool_with_target(self, monkeypatch, sample_robot_overview):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.list_robots = AsyncMock(return_value=[sample_robot_overview])

        with patch.object(main_module, "get_patronus_client", return_value=mock_client):
            result = await main_module.get_patronus_robots("ultimate", "feature/test", target_branch="master")

        mock_client.list_robots.assert_called_once_with(
            repository="ultimate",
            source_branch="feature/test",
            target_branch="master",
        )

    async def test_get_patronus_robots_tool_empty(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.list_robots = AsyncMock(return_value=[])

        with patch.object(main_module, "get_patronus_client", return_value=mock_client):
            result = await main_module.get_patronus_robots("ultimate", "feature/test")

        parsed = json.loads(result)
        assert parsed == []

    async def test_get_patronus_robot_details_tool(self, monkeypatch, sample_robot_overview, sample_teamcity_checks, sample_robot_problems):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.get_robot = AsyncMock(return_value=sample_robot_overview)
        mock_client.get_robot_teamcity_checks = AsyncMock(return_value=sample_teamcity_checks)
        mock_client.get_robot_problems = AsyncMock(return_value=sample_robot_problems)

        with patch.object(main_module, "get_patronus_client", return_value=mock_client):
            result = await main_module.get_patronus_robot_details("cc448634-880e-411f-9ee6-347e9a6087ac")

        parsed = json.loads(result)
        assert parsed["robot"]["id"] == "cc448634-880e-411f-9ee6-347e9a6087ac"
        assert parsed["robot"]["status"] == "SUCCESSFUL"
        assert len(parsed["teamcity_checks"]) == 2
        assert len(parsed["problems"]["problems"]) == 1

    async def test_get_patronus_robot_details_tool_returns_formatted_json(self, monkeypatch, sample_robot_overview, sample_teamcity_checks, sample_robot_problems):
        monkeypatch.setenv("SPACE_TOKEN", "test-token")

        mock_client = MagicMock()
        mock_client.get_robot = AsyncMock(return_value=sample_robot_overview)
        mock_client.get_robot_teamcity_checks = AsyncMock(return_value=sample_teamcity_checks)
        mock_client.get_robot_problems = AsyncMock(return_value=sample_robot_problems)

        with patch.object(main_module, "get_patronus_client", return_value=mock_client):
            result = await main_module.get_patronus_robot_details("some-id")

        # Should be pretty-printed JSON with indentation
        assert "\n" in result
        assert "  " in result
