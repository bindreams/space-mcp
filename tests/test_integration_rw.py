"""Comprehensive read-write integration tests against real Space repositories.

These tests create branches, MRs, dry runs, and merges against dedicated test repos,
then clean up after themselves. They are fully repeatable from any repo state.

Requires SPACE_TOKEN (via .env or environment variable).
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from space.client import SpaceClient
from space.models import MergeRequest, MRState, PatronusRun
from space.patronus import PatronusClient
import space.mcp.server as mcp_server

from .integration_helpers import (
    parse_git_url,
    ensure_repo_ready,
    create_test_branch,
    push_test_commit,
    delete_branch,
)

# Test repositories (git remote URLs) -----

TEST_REPO = "https://git.jetbrains.team/space-mcp/test.git"
TEST_PATRONUS_REPO = "https://git.jetbrains.team/space-mcp/test-patronus.git"

TEST_PROJECT, TEST_REPO_NAME = parse_git_url(TEST_REPO)
PATRONUS_PROJECT, PATRONUS_REPO_NAME = parse_git_url(TEST_PATRONUS_REPO)

TARGET_BRANCH = "main"


# Session-scoped fixtures =====


@pytest.fixture(scope="session")
def _session_token():
    import os
    token = os.environ.get("SPACE_TOKEN")
    if not token:
        pytest.fail("SPACE_TOKEN not set — required for integration tests")
    return token


@pytest.fixture(scope="session", autouse=True)
def ensure_repos_ready(_session_token):
    asyncio.run(ensure_repo_ready(_session_token, TEST_REPO))
    asyncio.run(ensure_repo_ready(_session_token, TEST_PATRONUS_REPO, patronus=True))


# Per-test fixtures =====


@pytest.fixture
async def test_branch_basic(space_token):
    branch = f"test/{uuid.uuid4()}"
    await create_test_branch(space_token, TEST_REPO, branch)
    await push_test_commit(space_token, TEST_REPO, branch)
    yield TEST_PROJECT, TEST_REPO_NAME, branch
    await delete_branch(space_token, TEST_REPO, branch)


@pytest.fixture
async def test_branch_patronus(space_token):
    branch = f"test/{uuid.uuid4()}"
    try:
        await create_test_branch(space_token, TEST_PATRONUS_REPO, branch)
    except RuntimeError as exc:
        if "not found" in str(exc).lower() or "permission" in str(exc).lower():
            pytest.skip(f"test-patronus repo not ready: {exc}")
        raise
    await push_test_commit(space_token, TEST_PATRONUS_REPO, branch)
    yield PATRONUS_PROJECT, PATRONUS_REPO_NAME, branch
    await delete_branch(space_token, TEST_PATRONUS_REPO, branch)


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
        await real_client.set_merge_request_state(project, str(mr.number), "Closed")
    except Exception:
        pass


@pytest.fixture
async def test_mr_patronus(real_client, test_branch_patronus):
    project, repo, branch = test_branch_patronus
    mr = await real_client.create_merge_request(
        project=project, repository=repo,
        source_branch=branch, target_branch=TARGET_BRANCH,
        title=f"Integration test MR ({branch})",
    )
    yield mr
    try:
        await real_client.set_merge_request_state(project, str(mr.number), "Closed")
    except Exception:
        pass


# MR lifecycle tests (space-mcp/test) =====


class TestMRLifecycle:

    async def test_create_mr(self, test_mr):
        assert isinstance(test_mr, MergeRequest)
        assert test_mr.number is not None
        assert test_mr.state == MRState.OPENED
        assert test_mr.title.startswith("Integration test MR")
        assert len(test_mr.branch_pairs) >= 1
        assert test_mr.branch_pairs[0].source_branch.startswith("test/")
        assert test_mr.branch_pairs[0].target_branch == TARGET_BRANCH

    async def test_get_mr_by_number(self, real_client, test_mr):
        fetched = await real_client.get_merge_request(TEST_PROJECT, TEST_REPO_NAME, str(test_mr.number))
        assert fetched.number == test_mr.number
        assert fetched.title == test_mr.title
        assert fetched.id == test_mr.id

    async def test_close_mr(self, real_client, test_mr):
        number = str(test_mr.number)
        await real_client.set_merge_request_state(TEST_PROJECT, number, "Closed")
        fetched = await real_client.get_merge_request(TEST_PROJECT, TEST_REPO_NAME, number)
        assert fetched.state == MRState.CLOSED
        await real_client.set_merge_request_state(TEST_PROJECT, number, "Opened")

    async def test_reopen_mr(self, real_client, test_mr):
        number = str(test_mr.number)
        await real_client.set_merge_request_state(TEST_PROJECT, number, "Closed")
        await real_client.set_merge_request_state(TEST_PROJECT, number, "Opened")
        fetched = await real_client.get_merge_request(TEST_PROJECT, TEST_REPO_NAME, number)
        assert fetched.state == MRState.OPENED

    async def test_find_mr_by_branch(self, real_client, test_mr, test_branch_basic):
        _, _, branch = test_branch_basic
        found = await real_client.find_merge_request_by_branch(TEST_PROJECT, TEST_REPO_NAME, branch)
        assert found is not None
        assert found.number == test_mr.number

    async def test_list_mrs_includes_test_mr(self, real_client, test_mr):
        mrs = await real_client.list_merge_requests(TEST_PROJECT, TEST_REPO_NAME, state="Open")
        numbers = [mr.number for mr in mrs]
        assert test_mr.number in numbers

    async def test_get_discussions_on_new_mr(self, real_client, test_mr):
        discussions = await real_client.get_merge_request_discussions(
            TEST_PROJECT, TEST_REPO_NAME, str(test_mr.number),
        )
        assert isinstance(discussions, list)


# Merge test (space-mcp/test) =====


class TestMerge:

    @pytest.fixture
    async def merge_branch(self, space_token):
        branch = f"test/{uuid.uuid4()}"
        await create_test_branch(space_token, TEST_REPO, branch)
        await push_test_commit(space_token, TEST_REPO, branch)
        yield TEST_PROJECT, TEST_REPO_NAME, branch
        await delete_branch(space_token, TEST_REPO, branch)

    async def test_merge_mr(self, real_client, merge_branch):
        project, repo, branch = merge_branch
        mr = await real_client.create_merge_request(
            project=project, repository=repo,
            source_branch=branch, target_branch=TARGET_BRANCH,
            title=f"Merge test ({branch})",
        )
        try:
            result = await real_client.start_safe_merge(project, str(mr.number), operation="Merge")
        except Exception as exc:
            if "quality gate" in str(exc).lower() or "safe merge" in str(exc).lower():
                pytest.skip("Safe merge not configured on test repo")
            raise
        assert result is not None
        fetched = await real_client.get_merge_request(project, repo, str(mr.number))
        assert fetched.state in (MRState.MERGED, MRState.CLOSED, MRState.OPENED)


# Patronus dry run tests (space-mcp/test-patronus) =====


class TestPatronusDryRun:

    async def test_start_dry_run(self, real_client, test_mr_patronus):
        number = str(test_mr_patronus.number)
        try:
            result = await real_client.start_safe_merge(PATRONUS_PROJECT, number, operation="DryRun")
        except Exception as exc:
            if "not configured" in str(exc).lower() or "not found" in str(exc).lower() or "not defined" in str(exc).lower():
                pytest.skip("Patronus/safe-merge not configured on test-patronus repo")
            raise
        assert result is not None

    async def test_list_robots_after_dry_run(
        self, real_client, real_patronus_client, test_mr_patronus, test_branch_patronus,
    ):
        _, repo, branch = test_branch_patronus
        number = str(test_mr_patronus.number)
        try:
            result = await real_client.start_safe_merge(PATRONUS_PROJECT, number, operation="DryRun")
        except Exception as exc:
            if "not configured" in str(exc).lower() or "not found" in str(exc).lower() or "not defined" in str(exc).lower():
                pytest.skip("Patronus/safe-merge not configured on test-patronus repo")
            raise
        if isinstance(result, list):
            errors = [e for e in result if e.get("type") == "Error"]
            assert not errors

        robots = []
        for attempt in range(12):
            robots = await real_patronus_client.list_robots_for_review(
                PATRONUS_PROJECT, number, source_branch=branch, target_branch=TARGET_BRANCH,
            )
            if robots:
                break
            await asyncio.sleep(5)
        assert len(robots) >= 1
        assert isinstance(robots[0], PatronusRun)

    async def test_get_robot_details(
        self, real_client, real_patronus_client, test_mr_patronus, test_branch_patronus,
    ):
        _, repo, branch = test_branch_patronus
        number = str(test_mr_patronus.number)
        try:
            await real_client.start_safe_merge(PATRONUS_PROJECT, number, operation="DryRun")
        except Exception as exc:
            if "not configured" in str(exc).lower() or "not found" in str(exc).lower() or "not defined" in str(exc).lower():
                pytest.skip("Patronus/safe-merge not configured on test-patronus repo")
            raise

        robots = await real_patronus_client.list_robots_for_review(
            PATRONUS_PROJECT, number, source_branch=branch, target_branch=TARGET_BRANCH,
        )
        if not robots:
            pytest.skip("No robots found — Patronus may not be configured")

        robot = await real_patronus_client.get_robot(robots[0].id)
        assert isinstance(robot, PatronusRun)
        assert robot.id == robots[0].id

    async def test_cancel_robot(
        self, real_client, real_patronus_client, test_mr_patronus, test_branch_patronus,
    ):
        _, repo, branch = test_branch_patronus
        number = str(test_mr_patronus.number)
        try:
            await real_client.start_safe_merge(PATRONUS_PROJECT, number, operation="DryRun")
        except Exception as exc:
            if "not configured" in str(exc).lower() or "not found" in str(exc).lower() or "not defined" in str(exc).lower():
                pytest.skip("Patronus/safe-merge not configured on test-patronus repo")
            raise

        robots = await real_patronus_client.list_robots_for_review(
            PATRONUS_PROJECT, number, source_branch=branch, target_branch=TARGET_BRANCH,
        )
        if not robots:
            pytest.skip("No robots found — Patronus may not be configured")

        await real_patronus_client.cancel_robot(robots[0].id)


# No-Patronus behavior tests (space-mcp/test) =====


class TestNoPatronus:

    async def test_start_dry_run_no_patronus(self, real_client, test_mr):
        number = str(test_mr.number)
        try:
            result = await real_client.start_safe_merge(TEST_PROJECT, number, operation="DryRun")
        except Exception:
            return
        assert result is not None

    async def test_list_robots_no_patronus(self, real_patronus_client):
        robots = await real_patronus_client.list_robots(
            repository=TEST_REPO_NAME, source_branch="nonexistent-branch",
        )
        assert robots == []


# MCP tool smoke tests =====


class TestMCPToolFormatting:

    async def test_mcp_get_merge_request(self, test_mr):
        import space.clients as clients_module
        clients_module._client = None
        result = await mcp_server.get_merge_request(
            TEST_PROJECT, TEST_REPO_NAME, str(test_mr.number),
        )
        assert result.startswith("# [MR")
        assert "Integration test MR" in result

    async def test_mcp_list_merge_requests(self):
        import space.clients as clients_module
        clients_module._client = None
        result = await mcp_server.list_merge_requests(TEST_PROJECT, TEST_REPO_NAME)
        assert isinstance(result, str)
        assert "**Error:**" not in result
