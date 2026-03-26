"""End-to-end tests for MCP server tool formatting.

Requires SPACE_TOKEN environment variable to be set (via .env or export).
"""
from __future__ import annotations

import uuid

import pytest

import space.mcp.server as mcp_server

from tests.e2e_helpers import (
    parse_git_url,
    create_test_branch,
    push_test_commit,
    delete_branch,
)

TEST_REPO = "https://git.jetbrains.team/space-mcp/test.git"
TEST_PROJECT, TEST_REPO_NAME = parse_git_url(TEST_REPO)
TARGET_BRANCH = "main"


@pytest.fixture
async def test_branch_basic(space_token):
    branch = f"test/{uuid.uuid4()}"
    await create_test_branch(space_token, TEST_REPO, branch)
    await push_test_commit(space_token, TEST_REPO, branch)
    yield TEST_PROJECT, TEST_REPO_NAME, branch
    await delete_branch(space_token, TEST_REPO, branch)


@pytest.fixture
async def test_mr(real_client, test_branch_basic):
    project, repo, branch = test_branch_basic
    mr = await real_client.create_merge_request(
        project=project, repository=repo,
        source_branch=branch, target_branch=TARGET_BRANCH,
        title=f"Integration test MR ({branch})",
    )
    yield mr
    try:
        await real_client.set_merge_request_state(project, str(mr.number), "Deleted")
    except Exception:
        pass


@pytest.mark.e2e
class TestMCPToolFormatting:

    async def test_mcp_get_merge_request(self, test_mr):
        import space.clients as clients_module
        clients_module._client = None
        result = await mcp_server.get_merge_request(
            TEST_PROJECT, TEST_REPO_NAME, str(test_mr.number),
        )
        assert result.startswith("# [MR")
        assert "Integration test MR" in result

    async def test_mcp_get_merge_requests(self):
        import space.clients as clients_module
        clients_module._client = None
        result = await mcp_server.get_merge_requests(TEST_PROJECT, TEST_REPO_NAME)
        assert isinstance(result, str)
        assert "**Error:**" not in result
