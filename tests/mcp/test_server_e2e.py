"""End-to-end tests for MCP server tool formatting.

Requires SPACE_TOKEN environment variable to be set (via .env or export).
"""
from __future__ import annotations

import os

import pytest

from space.mcp.server import SpaceMCP

from tests.conftest import TEST_RW_PROJECT, TEST_RW_REPO_NAME


@pytest.fixture()
def mcp():
    return SpaceMCP(os.environ.get("SPACE_TOKEN"))


@pytest.mark.e2e
class TestMCPToolFormatting:

    async def test_mcp_get_merge_request(self, mcp, test_mr):
        result = await mcp.get_merge_request(
            TEST_RW_PROJECT,
            TEST_RW_REPO_NAME,
            str(test_mr.number),
        )
        assert result.startswith("# [MR")
        assert "Integration test MR" in result

    async def test_mcp_get_merge_requests(self, mcp):
        result = await mcp.get_merge_requests(TEST_RW_PROJECT, TEST_RW_REPO_NAME)
        assert isinstance(result, str)
        assert "**Error:**" not in result
