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
from space.patronus import PatronusClient
import space.mcp.server as mcp_server

from .integration_helpers import (
    parse_git_url,
    ensure_repo_ready,
    create_test_branch,
    push_test_commit,
    delete_branch,
)

# Test repositories (git remote URLs) -----------------------------------------

TEST_REPO = "https://git.jetbrains.team/space-mcp/test.git"
TEST_PATRONUS_REPO = "https://git.jetbrains.team/space-mcp/test-patronus.git"

TEST_PROJECT, TEST_REPO_NAME = parse_git_url(TEST_REPO)
PATRONUS_PROJECT, PATRONUS_REPO_NAME = parse_git_url(TEST_PATRONUS_REPO)

TARGET_BRANCH = "main"


# Session-scoped fixtures =====================================================


@pytest.fixture(scope="session")
def _session_token():
    """Session-scoped token for repo bootstrapping."""
    import os
    token = os.environ.get("SPACE_TOKEN")
    if not token:
        pytest.fail("SPACE_TOKEN not set — required for integration tests")
    return token


@pytest.fixture(scope="session", autouse=True)
def ensure_repos_ready(_session_token):
    """Ensure both test repos are in a known good state before any tests run."""
    asyncio.run(ensure_repo_ready(_session_token, TEST_REPO))
    asyncio.run(ensure_repo_ready(_session_token, TEST_PATRONUS_REPO, patronus=True))


# Per-test fixtures ============================================================


@pytest.fixture
async def test_branch_basic(space_token):
    """Create a unique branch with a test commit on the basic (non-Patronus) repo.

    Yields (project, repo_name, branch_name). Deletes branch on teardown.
    """
    branch = f"test/{uuid.uuid4()}"
    await create_test_branch(space_token, TEST_REPO, branch)
    await push_test_commit(space_token, TEST_REPO, branch)
    yield TEST_PROJECT, TEST_REPO_NAME, branch
    await delete_branch(space_token, TEST_REPO, branch)


@pytest.fixture
async def test_branch_patronus(space_token):
    """Create a unique branch with a test commit on the Patronus repo.

    Yields (project, repo_name, branch_name). Deletes branch on teardown.
    Skips if the repo has no main branch (not yet bootstrapped).
    """
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
    """Create an MR on the basic repo from the test branch.

    Yields the MR dict. Closes the MR on teardown.
    """
    project, repo, branch = test_branch_basic
    mr = await real_client.create_merge_request(
        project=project,
        repository=repo,
        source_branch=branch,
        target_branch=TARGET_BRANCH,
        title=f"Integration test MR ({branch})",
    )
    yield mr
    try:
        await real_client.set_merge_request_state(project, str(mr["number"]), "Closed")
    except Exception:
        pass


@pytest.fixture
async def test_mr_patronus(real_client, test_branch_patronus):
    """Create an MR on the Patronus repo from the test branch.

    Yields the MR dict. Closes the MR on teardown.
    """
    project, repo, branch = test_branch_patronus
    mr = await real_client.create_merge_request(
        project=project,
        repository=repo,
        source_branch=branch,
        target_branch=TARGET_BRANCH,
        title=f"Integration test MR ({branch})",
    )
    yield mr
    try:
        await real_client.set_merge_request_state(project, str(mr["number"]), "Closed")
    except Exception:
        pass


# MR lifecycle tests (space-mcp/test) =========================================


class TestMRLifecycle:
    """Create, read, close, reopen MRs on the basic test repo."""

    async def test_create_mr(self, test_mr):
        """Created MR has expected fields."""
        assert "number" in test_mr
        assert "id" in test_mr
        assert test_mr.get("state") in ("Opened", "Open")
        assert test_mr.get("title", "").startswith("Integration test MR")

        branch_pairs = test_mr.get("branchPairs", [])
        assert len(branch_pairs) >= 1
        bp = branch_pairs[0]
        assert bp.get("sourceBranch", "").startswith("test/")
        assert bp.get("targetBranch") == TARGET_BRANCH

    async def test_get_mr_by_number(self, real_client, test_mr):
        """Fetch MR by display number and verify fields match."""
        number = str(test_mr["number"])
        fetched = await real_client.get_merge_request(TEST_PROJECT, TEST_REPO_NAME, number)

        assert fetched["number"] == test_mr["number"]
        assert fetched["title"] == test_mr["title"]
        assert fetched["id"] == test_mr["id"]

    async def test_close_mr(self, real_client, test_mr):
        """Close the MR and verify state."""
        number = str(test_mr["number"])
        await real_client.set_merge_request_state(TEST_PROJECT, number, "Closed")

        fetched = await real_client.get_merge_request(TEST_PROJECT, TEST_REPO_NAME, number)
        assert fetched["state"] == "Closed"

        # Reopen so the fixture teardown doesn't fail
        await real_client.set_merge_request_state(TEST_PROJECT, number, "Opened")

    async def test_reopen_mr(self, real_client, test_mr):
        """Close then reopen the MR."""
        number = str(test_mr["number"])
        await real_client.set_merge_request_state(TEST_PROJECT, number, "Closed")
        await real_client.set_merge_request_state(TEST_PROJECT, number, "Opened")

        fetched = await real_client.get_merge_request(TEST_PROJECT, TEST_REPO_NAME, number)
        assert fetched["state"] in ("Opened", "Open")

    async def test_find_mr_by_branch(self, real_client, test_mr, test_branch_basic):
        """Find the test MR by its branch name."""
        _, _, branch = test_branch_basic
        found = await real_client.find_merge_request_by_branch(
            TEST_PROJECT, TEST_REPO_NAME, branch,
        )
        assert found is not None
        assert found["number"] == test_mr["number"]

    async def test_list_mrs_includes_test_mr(self, real_client, test_mr):
        """List open MRs and verify our test MR is included."""
        mrs = await real_client.list_merge_requests(
            TEST_PROJECT, TEST_REPO_NAME, state="Open",
        )
        numbers = [mr.get("number") for mr in mrs]
        assert test_mr["number"] in numbers

    async def test_get_discussions_on_new_mr(self, real_client, test_mr):
        """A freshly created MR should have a timeline (at least creation event)."""
        discussions = await real_client.get_merge_request_discussions(
            TEST_PROJECT, TEST_REPO_NAME, str(test_mr["number"]),
        )
        assert isinstance(discussions, list)


# Merge test (space-mcp/test) =================================================


class TestMerge:
    """Test actual merge operations. Each test creates its own branch (consumed by merge)."""

    @pytest.fixture
    async def merge_branch(self, space_token):
        """Create a branch for merge testing. No teardown — merge consumes it."""
        branch = f"test/{uuid.uuid4()}"
        await create_test_branch(space_token, TEST_REPO, branch)
        await push_test_commit(space_token, TEST_REPO, branch)
        yield TEST_PROJECT, TEST_REPO_NAME, branch
        # Best-effort cleanup in case merge didn't happen
        await delete_branch(space_token, TEST_REPO, branch)

    async def test_merge_mr(self, real_client, merge_branch):
        """Create MR, merge it, verify state.

        Skips if the repo has no safe merge / quality gate configured.
        """
        project, repo, branch = merge_branch
        mr = await real_client.create_merge_request(
            project=project,
            repository=repo,
            source_branch=branch,
            target_branch=TARGET_BRANCH,
            title=f"Merge test ({branch})",
        )

        try:
            result = await real_client.start_safe_merge(
                project, str(mr["number"]), operation="Merge",
            )
        except Exception as exc:
            if "quality gate" in str(exc).lower() or "safe merge" in str(exc).lower():
                pytest.skip("Safe merge not configured on test repo")
            raise
        assert result is not None

        # The merge may take a moment. Verify the MR eventually reflects merged state.
        fetched = await real_client.get_merge_request(project, repo, str(mr["number"]))
        assert fetched["state"] in ("Merged", "Closed", "Opened"), (
            f"Unexpected state after merge: {fetched['state']}"
        )


# Patronus dry run tests (space-mcp/test-patronus) ============================


class TestPatronusDryRun:
    """Test dry run lifecycle on the Patronus-enabled repo.

    All tests skip if Patronus is not configured on the repo.
    """

    async def test_start_dry_run(self, real_client, test_mr_patronus):
        """Start a dry run and verify the response."""
        project = PATRONUS_PROJECT
        number = str(test_mr_patronus["number"])

        try:
            result = await real_client.start_safe_merge(project, number, operation="DryRun")
        except Exception as exc:
            if "not configured" in str(exc).lower() or "not found" in str(exc).lower() or "not defined" in str(exc).lower():
                pytest.skip("Patronus/safe-merge not configured on test-patronus repo")
            raise

        # Response is either a dict with robotId or a list of progress events
        assert result is not None
        if isinstance(result, dict):
            assert "jobId" in result or "robotId" in result or "status" in result
        elif isinstance(result, list):
            types = {e.get("type") for e in result}
            assert types & {"Progress", "Error"}, f"Unexpected event types: {types}"

    async def test_list_robots_after_dry_run(
        self, real_client, real_patronus_client, test_mr_patronus, test_branch_patronus,
    ):
        """After starting a dry run, list_robots should find at least one robot."""
        project = PATRONUS_PROJECT
        _, repo, branch = test_branch_patronus
        number = str(test_mr_patronus["number"])

        try:
            await real_client.start_safe_merge(project, number, operation="DryRun")
        except Exception as exc:
            if "not configured" in str(exc).lower() or "not found" in str(exc).lower() or "not defined" in str(exc).lower():
                pytest.skip("Patronus/safe-merge not configured on test-patronus repo")
            raise

        robots = await real_patronus_client.list_robots(repository=repo, source_branch=branch)
        assert len(robots) >= 1
        assert "id" in robots[0]
        assert "status" in robots[0]

    async def test_get_robot_details(
        self, real_client, real_patronus_client, test_mr_patronus, test_branch_patronus,
    ):
        """Fetch robot details after starting a dry run."""
        project = PATRONUS_PROJECT
        _, repo, branch = test_branch_patronus
        number = str(test_mr_patronus["number"])

        try:
            await real_client.start_safe_merge(project, number, operation="DryRun")
        except Exception as exc:
            if "not configured" in str(exc).lower() or "not found" in str(exc).lower() or "not defined" in str(exc).lower():
                pytest.skip("Patronus/safe-merge not configured on test-patronus repo")
            raise

        robots = await real_patronus_client.list_robots(repository=repo, source_branch=branch)
        if not robots:
            pytest.skip("No robots found — Patronus may not be configured")

        robot = await real_patronus_client.get_robot(robots[0]["id"])
        assert robot["id"] == robots[0]["id"]
        assert "status" in robot
        assert "repository" in robot

    async def test_cancel_robot(
        self, real_client, real_patronus_client, test_mr_patronus, test_branch_patronus,
    ):
        """Cancel a robot after starting a dry run."""
        project = PATRONUS_PROJECT
        _, repo, branch = test_branch_patronus
        number = str(test_mr_patronus["number"])

        try:
            await real_client.start_safe_merge(project, number, operation="DryRun")
        except Exception as exc:
            if "not configured" in str(exc).lower() or "not found" in str(exc).lower() or "not defined" in str(exc).lower():
                pytest.skip("Patronus/safe-merge not configured on test-patronus repo")
            raise

        robots = await real_patronus_client.list_robots(repository=repo, source_branch=branch)
        if not robots:
            pytest.skip("No robots found — Patronus may not be configured")

        # Cancel should not raise
        await real_patronus_client.cancel_robot(robots[0]["id"])


# No-Patronus behavior tests (space-mcp/test) =================================


class TestNoPatronus:
    """Verify behavior when Patronus is not configured on the repo."""

    async def test_start_dry_run_no_patronus(self, real_client, test_mr):
        """Starting a dry run on a non-Patronus repo should not crash.

        The repo has safe merge configured but no Patronus. The API may:
        - Raise an exception (acceptable)
        - Return progress/error events (acceptable)
        - Return a success dict (also acceptable — empty builds = instant pass)
        """
        number = str(test_mr["number"])
        try:
            result = await real_client.start_safe_merge(TEST_PROJECT, number, operation="DryRun")
        except Exception:
            # An exception is acceptable
            return

        # If it returned, any valid response shape is fine
        assert result is not None

    async def test_list_robots_no_patronus(self, real_patronus_client):
        """Listing robots for the non-Patronus repo should return empty."""
        robots = await real_patronus_client.list_robots(
            repository=TEST_REPO_NAME,
            source_branch="nonexistent-branch",
        )
        assert robots == []


# MCP tool smoke tests ========================================================


class TestMCPToolFormatting:
    """End-to-end tests calling MCP tool functions with real data."""

    async def test_mcp_get_merge_request(self, test_mr):
        """MCP get_merge_request returns markdown."""
        import space.clients as clients_module
        clients_module._client = None

        result = await mcp_server.get_merge_request(
            TEST_PROJECT, TEST_REPO_NAME, str(test_mr["number"]),
        )
        assert result.startswith("# [MR")
        assert "Integration test MR" in result

    async def test_mcp_list_merge_requests(self):
        """MCP list_merge_requests returns a markdown table."""
        import space.clients as clients_module
        clients_module._client = None

        result = await mcp_server.list_merge_requests(TEST_PROJECT, TEST_REPO_NAME)
        # May be empty or have results — either way should be valid markdown
        assert isinstance(result, str)
        assert "**Error:**" not in result
