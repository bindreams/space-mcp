"""End-to-end tests for MCP server tool formatting.

Requires SPACE_TOKEN environment variable to be set (via .env or export).
"""
from __future__ import annotations

import pytest

import space.mcp.server as mcp_server

from tests.conftest import TEST_RW_PROJECT, TEST_RW_REPO_NAME


@pytest.mark.e2e
class TestMCPToolFormatting:

    async def test_mcp_get_merge_request(self, test_mr):
        import space.clients as clients_module
        clients_module._client = None
        result = await mcp_server.get_merge_request(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, str(test_mr.number),
        )
        assert result.startswith("# [MR")
        assert "Integration test MR" in result

    async def test_mcp_get_merge_requests(self):
        import space.clients as clients_module
        clients_module._client = None
        result = await mcp_server.get_merge_requests(TEST_RW_PROJECT, TEST_RW_REPO_NAME)
        assert isinstance(result, str)
        assert "**Error:**" not in result
