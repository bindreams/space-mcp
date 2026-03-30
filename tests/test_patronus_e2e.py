"""End-to-end tests for PatronusClient against real Patronus API.

Requires SPACE_TOKEN environment variable to be set (via .env or export).
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
import pytest_asyncio

from space.models import (
    PatronusRun,
    RunStatus,
)

from .conftest import TEST_RW_PROJECT, TEST_RW_REPO_NAME, TARGET_BRANCH, _test_branch
from .e2e_helpers import ensure_repo_ready, parse_git_url, push_failing_commit

# Patronus-specific repos
TEST_PATRONUS_REPO = "https://git.jetbrains.team/space-mcp/test-patronus.git"
PATRONUS_PROJECT, PATRONUS_REPO_NAME = parse_git_url(TEST_PATRONUS_REPO)

_TERMINAL_STATUSES = {RunStatus.SUCCESS, RunStatus.FAILURE, RunStatus.CANCELLED}

# Session-scoped Patronus fixtures =====================================================================================


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def patronus_repo_ready(space_token_session):
    """Ensure test-patronus repo has .space.kts, safe-merge config, and quality gates."""
    await ensure_repo_ready(space_token_session, TEST_PATRONUS_REPO, patronus=True)


async def _start_dry_run(token, space_client, patronus_client, *, push_failing=False):
    """Create branch + MR + dry run in test-patronus. Return (run, project, repo, branch, mr)."""
    async with _test_branch(token, TEST_PATRONUS_REPO) as (project, repo, branch):
        if push_failing:
            await push_failing_commit(token, TEST_PATRONUS_REPO, branch)

        mr = await space_client.create_merge_request(
            project=project,
            repository=repo,
            source_branch=branch,
            target_branch=TARGET_BRANCH,
            title=f"Patronus e2e ({branch})",
        )
        try:
            result = await space_client.start_safe_merge(project, str(mr.number), operation="DryRun")
            if isinstance(result, list):
                errors = [e["message"] for e in result if e.get("type") == "Error"]
                if errors:
                    pytest.fail(f"start_safe_merge failed: {errors[0][:200]}")

            # Poll until run appears (up to 120s)
            run = None
            for _ in range(24):
                runs = await patronus_client.list_runs_for_review(
                    project,
                    mr.number,
                    source_branch=branch,
                    target_branch=TARGET_BRANCH,
                )
                if runs:
                    run = runs[0]
                    break
                await asyncio.sleep(5)

            if run is None:
                pytest.fail("Dry run not found after 120s")

            yield run, project, repo, branch, mr
        finally:
            await space_client.set_merge_request_state(project, str(mr.number), "Deleted")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def seeded_patronus_run(
    patronus_repo_ready, space_token_session, real_client_session, real_patronus_client_session
):
    """Session-scoped dry run in test-patronus (normal commit, may pass or be in progress)."""
    async for result in _start_dry_run(space_token_session, real_client_session, real_patronus_client_session):
        run, project, repo, branch, mr = result
        yield run
        # Teardown: cancel best-effort
        try:
            await real_patronus_client_session.cancel_run(run.id)
        except httpx.HTTPError:
            pass


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def completed_failed_run(
    patronus_repo_ready, space_token_session, real_client_session, real_patronus_client_session
):
    """Session-scoped dry run in test-patronus with FAIL_CI marker, waited to completion."""
    async for result in _start_dry_run(
        space_token_session, real_client_session, real_patronus_client_session, push_failing=True
    ):
        run, project, repo, branch, mr = result

        # Poll until terminal status (up to 5 min)
        for _ in range(30):
            run = await real_patronus_client_session.get_run(run.id)
            if run.status in _TERMINAL_STATUSES:
                break
            await asyncio.sleep(10)

        if run.status not in _TERMINAL_STATUSES:
            pytest.fail(f"Dry run did not complete after 5 min (status: {run.status})")
        if run.status != RunStatus.FAILURE:
            pytest.fail(
                f"Dry run completed with {run.status.value}, expected FAILURE — "
                f"check test-patronus CI setup (.space.kts + quality gates)"
            )
        yield run


# Read-only Patronus e2e tests =========================================================================================


@pytest.mark.e2e
class TestPatronusFailedRun:

    async def test_get_problems_returns_tuple(self, real_patronus_client, completed_failed_run):
        problems = await real_patronus_client.get_run_problems(completed_failed_run.id)
        assert isinstance(problems, tuple)
        for p in problems:
            assert p.title
            assert p.title != "?"

    async def test_failed_check_exists(self, real_patronus_client, completed_failed_run):
        checks = await real_patronus_client.get_run_teamcity_checks(completed_failed_run.id)
        failed_checks = [c for c in checks if c.status == RunStatus.FAILURE]
        assert len(failed_checks) >= 1

    @pytest.fixture
    async def failed_attempt_details(self, real_patronus_client, completed_failed_run):
        checks = await real_patronus_client.get_run_teamcity_checks(completed_failed_run.id)
        failed_checks = [c for c in checks if c.status == RunStatus.FAILURE]
        if not failed_checks:
            pytest.fail("No failed checks in completed failed run")
        failed_attempts = [a for a in failed_checks[0].attempts if a.status == RunStatus.FAILURE]
        if not failed_attempts:
            pytest.fail("No failed attempts in failed check")
        return await real_patronus_client.get_attempt_details(failed_attempts[-1].id)

    async def test_attempt_details_have_failed_test(self, failed_attempt_details):
        assert len(failed_attempt_details.failed_tests) >= 1
        for t in failed_attempt_details.failed_tests:
            assert t.name

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

    async def test_list_runs_for_repository(self, real_patronus_client, seeded_patronus_run):
        result = await real_patronus_client.list_runs(seeded_patronus_run.branch_pair.repository)
        assert isinstance(result, list)
        assert any(r.id == seeded_patronus_run.id for r in result)

    async def test_run_overview_structure(self, real_patronus_client, seeded_patronus_run):
        run = seeded_patronus_run
        assert isinstance(run, PatronusRun)
        assert run.status is not None

    async def test_get_run_details(self, real_patronus_client, seeded_patronus_run):
        run = await real_patronus_client.get_run(seeded_patronus_run.id)
        assert isinstance(run, PatronusRun)
        assert run.id == seeded_patronus_run.id

    async def test_get_run_teamcity_checks(self, real_patronus_client, seeded_patronus_run):
        checks = await real_patronus_client.get_run_teamcity_checks(seeded_patronus_run.id)
        assert isinstance(checks, list)

    async def test_cancel_finished_run_is_idempotent(self, real_patronus_client, completed_failed_run):
        await real_patronus_client.cancel_run(completed_failed_run.id)

    async def test_get_me(self, real_patronus_client):
        me = await real_patronus_client.get_me(TEST_RW_REPO_NAME)
        assert me["type"] in ("USER", "APPLICATION")
        assert "id" in me
        assert "name" in me


# Read-write Patronus e2e tests ========================================================================================


@pytest.fixture
async def test_branch_patronus(space_token):
    try:
        async with _test_branch(space_token, TEST_PATRONUS_REPO) as result:
            yield result
    except RuntimeError as exc:
        if "not found" in str(exc).lower() or "permission" in str(exc).lower():
            pytest.skip(f"test-patronus repo not ready: {exc}")
        raise


@pytest.fixture
async def test_mr_patronus(real_client, test_branch_patronus):
    project, repo, branch = test_branch_patronus
    mr = await real_client.create_merge_request(
        project=project,
        repository=repo,
        source_branch=branch,
        target_branch=TARGET_BRANCH,
        title=f"Integration test MR ({branch})",
    )
    yield mr
    await real_client.set_merge_request_state(project, str(mr.number), "Deleted")


@pytest.mark.e2e
class TestPatronusDryRun:

    async def test_start_dry_run(self, real_client, test_mr_patronus):
        number = str(test_mr_patronus.number)
        try:
            result = await real_client.start_safe_merge(PATRONUS_PROJECT, number, operation="DryRun")
        except Exception as exc:
            if "not configured" in str(exc).lower() or "not found" in str(exc).lower(
            ) or "not defined" in str(exc).lower():
                pytest.skip("Patronus/safe-merge not configured on test-patronus repo")
            raise
        assert result is not None

    async def test_list_runs_after_dry_run(
        self,
        real_client,
        real_patronus_client,
        test_mr_patronus,
        test_branch_patronus,
    ):
        _, repo, branch = test_branch_patronus
        number = str(test_mr_patronus.number)
        try:
            result = await real_client.start_safe_merge(PATRONUS_PROJECT, number, operation="DryRun")
        except Exception as exc:
            if "not configured" in str(exc).lower() or "not found" in str(exc).lower(
            ) or "not defined" in str(exc).lower():
                pytest.skip("Patronus/safe-merge not configured on test-patronus repo")
            raise
        if isinstance(result, list):
            errors = [e for e in result if e.get("type") == "Error"]
            assert not errors

        runs = []
        for attempt in range(12):
            runs = await real_patronus_client.list_runs_for_review(
                PATRONUS_PROJECT,
                number,
                source_branch=branch,
                target_branch=TARGET_BRANCH,
            )
            if runs:
                break
            await asyncio.sleep(5)
        assert len(runs) >= 1
        assert isinstance(runs[0], PatronusRun)

    async def test_get_run_details(
        self,
        real_client,
        real_patronus_client,
        test_mr_patronus,
        test_branch_patronus,
    ):
        _, repo, branch = test_branch_patronus
        number = str(test_mr_patronus.number)
        try:
            await real_client.start_safe_merge(PATRONUS_PROJECT, number, operation="DryRun")
        except Exception as exc:
            if "not configured" in str(exc).lower() or "not found" in str(exc).lower(
            ) or "not defined" in str(exc).lower():
                pytest.skip("Patronus/safe-merge not configured on test-patronus repo")
            raise

        runs = await real_patronus_client.list_runs_for_review(
            PATRONUS_PROJECT,
            number,
            source_branch=branch,
            target_branch=TARGET_BRANCH,
        )
        if not runs:
            pytest.skip("No runs found — Patronus may not be configured")

        run = await real_patronus_client.get_run(runs[0].id)
        assert isinstance(run, PatronusRun)
        assert run.id == runs[0].id

    async def test_cancel_run(
        self,
        real_client,
        real_patronus_client,
        test_mr_patronus,
        test_branch_patronus,
    ):
        _, repo, branch = test_branch_patronus
        number = str(test_mr_patronus.number)
        try:
            await real_client.start_safe_merge(PATRONUS_PROJECT, number, operation="DryRun")
        except Exception as exc:
            if "not configured" in str(exc).lower() or "not found" in str(exc).lower(
            ) or "not defined" in str(exc).lower():
                pytest.skip("Patronus/safe-merge not configured on test-patronus repo")
            raise

        runs = await real_patronus_client.list_runs_for_review(
            PATRONUS_PROJECT,
            number,
            source_branch=branch,
            target_branch=TARGET_BRANCH,
        )
        if not runs:
            pytest.skip("No runs found — Patronus may not be configured")

        await real_patronus_client.cancel_run(runs[0].id)


@pytest.mark.e2e
class TestNoPatronus:

    async def test_start_dry_run_no_patronus(self, real_client, test_mr):
        number = str(test_mr.number)
        try:
            result = await real_client.start_safe_merge(TEST_RW_PROJECT, number, operation="DryRun")
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException):
            return
        assert result is not None

    async def test_list_runs_no_patronus(self, real_patronus_client):
        runs = await real_patronus_client.list_runs(
            repository=TEST_RW_REPO_NAME,
            source_branch="nonexistent-branch",
        )
        assert runs == []
