"""End-to-end tests for PatronusClient against real Patronus API.

Requires SPACE_TOKEN environment variable to be set (via .env or export).
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from space.models import (
    PatronusRun,
    RunStatus,
)

from .e2e_helpers import (
    parse_git_url,
    create_test_branch,
    push_test_commit,
    delete_branch,
)

# Test repositories
TEST_PATRONUS_REPO = "https://git.jetbrains.team/space-mcp/test-patronus.git"
PATRONUS_PROJECT, PATRONUS_REPO_NAME = parse_git_url(TEST_PATRONUS_REPO)

TEST_REPO = "https://git.jetbrains.team/space-mcp/test.git"
TEST_PROJECT, TEST_REPO_NAME = parse_git_url(TEST_REPO)

TARGET_BRANCH = "main"


# Read-only Patronus e2e tests =====


@pytest.mark.e2e
class TestPatronusFailedRun:

    async def test_problems_have_title(self, real_patronus_client, failed_patronus_run):
        problems = await real_patronus_client.get_run_problems(failed_patronus_run.id)
        assert len(problems) > 0
        for p in problems:
            assert p.title
            assert p.title != "?"

    async def test_failed_check_exists(self, real_patronus_client, failed_patronus_run):
        checks = await real_patronus_client.get_run_teamcity_checks(failed_patronus_run.id)
        failed_checks = [c for c in checks if c.status == RunStatus.FAILURE]
        assert len(failed_checks) >= 1

    @pytest.fixture
    async def failed_attempt_details(self, real_patronus_client, failed_patronus_run):
        checks = await real_patronus_client.get_run_teamcity_checks(failed_patronus_run.id)
        failed_checks = [c for c in checks if c.status == RunStatus.FAILURE]
        if not failed_checks:
            pytest.skip("No failed checks in this run")
        failed_attempts = [a for a in failed_checks[0].attempts if a.status == RunStatus.FAILURE]
        if not failed_attempts:
            pytest.skip("No failed attempts in failed check")
        return await real_patronus_client.get_attempt_details(failed_attempts[-1].id)

    async def test_attempt_details_have_failed_test(self, failed_attempt_details):
        assert len(failed_attempt_details.failed_tests) >= 1
        for t in failed_attempt_details.failed_tests:
            assert t.name  # non-empty name

    async def test_attempt_details_have_content(self, failed_attempt_details):
        all_text = ""
        for t in failed_attempt_details.failed_tests:
            all_text += t.name + " "
        for b in failed_attempt_details.failed_builds:
            for p in b.problems:
                all_text += p + " "
        assert len(all_text.strip()) > 0


@pytest.mark.e2e
class TestPatronusIntegration:

    async def test_list_runs_for_repository(self, real_patronus_client):
        result = await real_patronus_client.list_runs(PATRONUS_REPO_NAME)
        assert isinstance(result, list)
        if not result:
            pytest.skip("No runs in test-patronus yet — run TestPatronusDryRun first")
        assert len(result) > 0

    async def test_run_overview_structure(self, real_patronus_client):
        runs = await real_patronus_client.list_runs(PATRONUS_REPO_NAME)
        if not runs:
            pytest.skip("No runs found")
        run = runs[0]
        assert isinstance(run, PatronusRun)
        assert run.status is not None

    async def test_get_run_details(self, real_patronus_client):
        runs = await real_patronus_client.list_runs(PATRONUS_REPO_NAME)
        if not runs:
            pytest.skip("No runs found")
        run = await real_patronus_client.get_run(runs[0].id)
        assert isinstance(run, PatronusRun)
        assert run.id == runs[0].id

    async def test_get_run_teamcity_checks(self, real_patronus_client):
        runs = await real_patronus_client.list_runs(PATRONUS_REPO_NAME)
        if not runs:
            pytest.skip("No runs found")
        checks = await real_patronus_client.get_run_teamcity_checks(runs[0].id)
        assert isinstance(checks, list)

    async def test_cancel_finished_run_is_idempotent(self, real_patronus_client, failed_patronus_run):
        await real_patronus_client.cancel_run(failed_patronus_run.id)

    async def test_get_me(self, real_patronus_client):
        me = await real_patronus_client.get_me(TEST_REPO_NAME)
        assert me["type"] in ("USER", "APPLICATION")
        assert "id" in me
        assert "name" in me


# Read-write Patronus e2e tests =====


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
async def test_mr_patronus(real_client, test_branch_patronus):
    project, repo, branch = test_branch_patronus
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


@pytest.fixture
async def test_mr_basic(real_client, space_token):
    branch = f"test/{uuid.uuid4()}"
    await create_test_branch(space_token, TEST_REPO, branch)
    await push_test_commit(space_token, TEST_REPO, branch)
    mr = await real_client.create_merge_request(
        project=TEST_PROJECT, repository=TEST_REPO_NAME,
        source_branch=branch, target_branch=TARGET_BRANCH,
        title=f"Integration test MR ({branch})",
    )
    yield mr
    try:
        await real_client.set_merge_request_state(TEST_PROJECT, str(mr.number), "Deleted")
    except Exception:
        pass
    await delete_branch(space_token, TEST_REPO, branch)


@pytest.mark.e2e
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

    async def test_list_runs_after_dry_run(
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

        runs = []
        for attempt in range(12):
            runs = await real_patronus_client.list_runs_for_review(
                PATRONUS_PROJECT, number, source_branch=branch, target_branch=TARGET_BRANCH,
            )
            if runs:
                break
            await asyncio.sleep(5)
        assert len(runs) >= 1
        assert isinstance(runs[0], PatronusRun)

    async def test_get_run_details(
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

        runs = await real_patronus_client.list_runs_for_review(
            PATRONUS_PROJECT, number, source_branch=branch, target_branch=TARGET_BRANCH,
        )
        if not runs:
            pytest.skip("No runs found — Patronus may not be configured")

        run = await real_patronus_client.get_run(runs[0].id)
        assert isinstance(run, PatronusRun)
        assert run.id == runs[0].id

    async def test_cancel_run(
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

        runs = await real_patronus_client.list_runs_for_review(
            PATRONUS_PROJECT, number, source_branch=branch, target_branch=TARGET_BRANCH,
        )
        if not runs:
            pytest.skip("No runs found — Patronus may not be configured")

        await real_patronus_client.cancel_run(runs[0].id)


@pytest.mark.e2e
class TestNoPatronus:

    async def test_start_dry_run_no_patronus(self, real_client, test_mr_basic):
        number = str(test_mr_basic.number)
        try:
            result = await real_client.start_safe_merge(TEST_PROJECT, number, operation="DryRun")
        except Exception:
            return
        assert result is not None

    async def test_list_runs_no_patronus(self, real_patronus_client):
        runs = await real_patronus_client.list_runs(
            repository=TEST_REPO_NAME, source_branch="nonexistent-branch",
        )
        assert runs == []
