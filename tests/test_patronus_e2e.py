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

# Run 494efb3a has a known failure
TEST_FAILED_RUN = "494efb3a-55cd-460a-9ed9-e0aa64a4b6c5"

# Test repositories
TEST_PATRONUS_REPO = "https://git.jetbrains.team/space-mcp/test-patronus.git"
PATRONUS_PROJECT, PATRONUS_REPO_NAME = parse_git_url(TEST_PATRONUS_REPO)

TEST_REPO = "https://git.jetbrains.team/space-mcp/test.git"
TEST_PROJECT, TEST_REPO_NAME = parse_git_url(TEST_REPO)

TARGET_BRANCH = "main"


# Read-only Patronus e2e tests =====


@pytest.mark.e2e
class TestPatronusFailedRun:

    async def test_problems_have_title(self, real_patronus_client):
        problems = await real_patronus_client.get_run_problems(TEST_FAILED_RUN)
        assert len(problems) > 0
        for p in problems:
            assert p.title
            assert p.title != "?"

    async def test_smoke_tests_check_failed(self, real_patronus_client):
        checks = await real_patronus_client.get_run_teamcity_checks(TEST_FAILED_RUN)
        smoke = [c for c in checks if c.config.build_configuration_id == "ijplatform_master_Idea_SmokeTests_Aggregator"]
        assert len(smoke) == 1
        assert smoke[0].status == RunStatus.FAILURE

    @pytest.fixture
    async def smoke_attempt_details(self, real_patronus_client):
        checks = await real_patronus_client.get_run_teamcity_checks(TEST_FAILED_RUN)
        smoke = [c for c in checks if c.config.build_configuration_id == "ijplatform_master_Idea_SmokeTests_Aggregator"]
        assert len(smoke) == 1
        failed = [a for a in smoke[0].attempts if a.status == RunStatus.FAILURE]
        assert len(failed) > 0
        return await real_patronus_client.get_attempt_details(failed[-1].id)

    async def test_attempt_details_have_failed_test(self, smoke_attempt_details):
        assert len(smoke_attempt_details.failed_tests) >= 1
        test_names = [t.name for t in smoke_attempt_details.failed_tests]
        assert any("IntelliJConfigurationFilesFormatTest" in name for name in test_names)

    async def test_attempt_details_reference_iml_file(self, smoke_attempt_details):
        all_text = ""
        for t in smoke_attempt_details.failed_tests:
            all_text += t.name + " "
        for b in smoke_attempt_details.failed_builds:
            for p in b.problems:
                all_text += p + " "
        assert "qodana" in all_text.lower() or "iml" in all_text.lower() or "IntelliJConfigurationFilesFormatTest" in all_text


@pytest.mark.e2e
class TestPatronusIntegration:

    async def test_list_runs_for_repository(self, real_patronus_client):
        result = await real_patronus_client.list_runs("ultimate")
        assert isinstance(result, list)
        assert len(result) > 0

    async def test_run_overview_structure(self, real_patronus_client):
        runs = await real_patronus_client.list_runs("ultimate")
        if not runs:
            pytest.skip("No runs found")
        run = runs[0]
        assert isinstance(run, PatronusRun)
        assert run.status is not None

    async def test_get_run_details(self, real_patronus_client):
        runs = await real_patronus_client.list_runs("ultimate")
        if not runs:
            pytest.skip("No runs found")
        run = await real_patronus_client.get_run(runs[0].id)
        assert isinstance(run, PatronusRun)
        assert run.id == runs[0].id

    async def test_get_run_teamcity_checks(self, real_patronus_client):
        runs = await real_patronus_client.list_runs("ultimate")
        if not runs:
            pytest.skip("No runs found")
        checks = await real_patronus_client.get_run_teamcity_checks(runs[0].id)
        assert isinstance(checks, list)

    async def test_cancel_finished_run_is_idempotent(self, real_patronus_client):
        await real_patronus_client.cancel_run(TEST_FAILED_RUN)

    async def test_get_me(self, real_patronus_client):
        me = await real_patronus_client.get_me("ultimate")
        assert me["type"] == "USER"
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
        await real_client.set_merge_request_state(project, str(mr.number), "Closed")
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
        await real_client.set_merge_request_state(TEST_PROJECT, str(mr.number), "Closed")
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
