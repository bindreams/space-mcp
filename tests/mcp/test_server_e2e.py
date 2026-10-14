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
        assert "merge-request:" in result
        assert "Integration test MR" in result

    async def test_mcp_get_merge_requests(self, mcp):
        result = await mcp.get_merge_requests(TEST_RW_PROJECT, TEST_RW_REPO_NAME)
        assert isinstance(result, str)
        assert "**Error:**" not in result


@pytest.mark.e2e
def test_mcp_main_strict_against_live_space(space_token, monkeypatch):
    """The production start-up path: main() resolves strict mode, then a tool reads live Space."""
    from unittest.mock import AsyncMock

    import space.mcp.server as server_module
    from space.models import enums
    from space.patronus import PatronusClient

    recorded: list[object] = []

    async def run_stdio_async(self, *args, **kwargs):
        recorded.append(enums.is_strict())
        recorded.append(await self.get_merge_requests(TEST_RW_PROJECT, TEST_RW_REPO_NAME, state="Opened", limit=0))

    monkeypatch.setenv("SPACE_STRICT", "1")
    # The server's PatronusClient uses the production URL; skip its warm-up so the test only touches Space.
    monkeypatch.setattr(PatronusClient, "warmup", AsyncMock())
    monkeypatch.setattr(SpaceMCP, "run_stdio_async", run_stdio_async)

    server_module.main()

    is_strict, result = recorded
    assert is_strict is True
    assert isinstance(result, str) and not result.startswith("**Error:**"), result
