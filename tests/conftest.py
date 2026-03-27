import copy
import os
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio

from space.client import SpaceClient
from space.models import SpaceAccount, RunStatus
from space.patronus import PatronusClient

from .sample_responses import (
    EMPTY_MERGE_REQUEST_LIST,
    SAMPLE_ATTEMPT_DETAILS,
    SAMPLE_CREATED_MERGE_REQUEST,
    SAMPLE_DISCUSSION_THREAD,
    SAMPLE_DISCUSSION_THREAD_WITH_ATTACHMENTS,
    SAMPLE_FEED_MESSAGES,
    SAMPLE_FEED_MESSAGES_WITH_ATTACHMENTS,
    SAMPLE_FEED_MESSAGES_WITH_GENERAL,
    SAMPLE_MERGE_REQUEST,
    SAMPLE_MERGE_REQUEST_LIST,
    SAMPLE_REVIEW_WITH_CHANNEL,
    SAMPLE_RUN_OVERVIEW,
    SAMPLE_RUN_PROBLEMS,
    SAMPLE_TEAMCITY_CHECKS_RESPONSE,
)

# SpaceAccount cache management ========================================================================================


@pytest.fixture(autouse=True)
def _clear_space_account_cache():
    """Clear SpaceAccount cache before each test to avoid cross-test leaks."""
    SpaceAccount.clear_cache()
    yield
    SpaceAccount.clear_cache()


def _prepopulate_accounts() -> dict[str, SpaceAccount]:
    """Pre-populate SpaceAccount cache with test accounts.

    Returns a dict of id -> SpaceAccount for reference.
    """
    accounts = [
        SpaceAccount(
            id="user-azhukova", username="azhukova", email="anna@test.com", first_name="Anna", last_name="Zhukova"
        ),
        SpaceAccount(id="user-jdoe", username="jdoe", email="john@test.com", first_name="John", last_name="Doe"),
    ]
    for a in accounts:
        SpaceAccount._cache_by_id[a.id] = a
        SpaceAccount._cache_by_username[a.username] = a
    return {a.id: a for a in accounts}


@pytest.fixture
def test_accounts():
    """Pre-populate SpaceAccount cache and return the test accounts."""
    return _prepopulate_accounts()


# Fixtures for unit tests (fake base URL, no real API calls) ===========================================================


@pytest_asyncio.fixture
async def space_client():
    """Create a SpaceClient instance with test token."""
    client = SpaceClient(token="test-token")
    yield client
    await client.aclose()


@pytest.fixture
def sample_merge_request():
    return copy.deepcopy(SAMPLE_MERGE_REQUEST)


@pytest.fixture
def sample_review_with_channel():
    return copy.deepcopy(SAMPLE_REVIEW_WITH_CHANNEL)


@pytest.fixture
def sample_feed_messages():
    return copy.deepcopy(SAMPLE_FEED_MESSAGES)


@pytest.fixture
def sample_discussion_thread():
    return copy.deepcopy(SAMPLE_DISCUSSION_THREAD)


@pytest.fixture
def sample_merge_request_list():
    return copy.deepcopy(SAMPLE_MERGE_REQUEST_LIST)


@pytest.fixture
def empty_merge_request_list():
    return copy.deepcopy(EMPTY_MERGE_REQUEST_LIST)


@pytest.fixture
def sample_feed_messages_with_general():
    return copy.deepcopy(SAMPLE_FEED_MESSAGES_WITH_GENERAL)


# Patronus fixtures ====================================================================================================


@pytest_asyncio.fixture
async def patronus_client(space_client):
    """Create a PatronusClient instance with test token and SpaceClient."""
    client = PatronusClient(token="test-token", space_client=space_client)
    yield client
    await client.aclose()


@pytest.fixture
def sample_run_overview():
    return copy.deepcopy(SAMPLE_RUN_OVERVIEW)


@pytest.fixture
def sample_runs_list(sample_run_overview):
    """Sample Patronus runs list response."""
    return {
        "me": {
            "type": "USER",
            "id": "user-azhukova",
            "name": "Anna Zhukova",
            "email": "anna.zhukova@jetbrains.com",
        },
        "robots": [sample_run_overview],
        "start": "2026-01-14T00:00:00Z",
        "end": "2026-01-16T00:00:00Z",
    }


@pytest.fixture
def sample_teamcity_checks_response():
    return copy.deepcopy(SAMPLE_TEAMCITY_CHECKS_RESPONSE)


@pytest.fixture
def sample_teamcity_checks(sample_teamcity_checks_response):
    """The extracted list of TeamCity checks (what PatronusClient.get_run_teamcity_checks returns)."""
    return sample_teamcity_checks_response["teamCityChecks"]


@pytest.fixture
def sample_run_problems():
    return copy.deepcopy(SAMPLE_RUN_PROBLEMS)


@pytest.fixture
def sample_attempt_details():
    return copy.deepcopy(SAMPLE_ATTEMPT_DETAILS)


@pytest.fixture
def sample_created_merge_request():
    return copy.deepcopy(SAMPLE_CREATED_MERGE_REQUEST)


@pytest.fixture
def sample_feed_messages_with_attachments():
    return copy.deepcopy(SAMPLE_FEED_MESSAGES_WITH_ATTACHMENTS)


@pytest.fixture
def sample_discussion_thread_with_attachments():
    return copy.deepcopy(SAMPLE_DISCUSSION_THREAD_WITH_ATTACHMENTS)


# Fixtures for integration tests (real API calls, loaded from .env) ====================================================


@pytest.fixture
def space_token():
    """Get SPACE_TOKEN from environment (loaded from .env by pytest-dotenv).

    Fails (not skips) if missing — a missing token is a CI configuration problem.
    """
    token = os.environ.get("SPACE_TOKEN")
    if not token:
        pytest.fail("SPACE_TOKEN not set — required for integration tests")
    return token


@pytest_asyncio.fixture
async def real_client(space_token):
    """Create a SpaceClient with real token for integration tests."""
    client = SpaceClient(token=space_token)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def real_patronus_client(space_token, real_client):
    """Create a PatronusClient with real token for integration tests."""
    base_url = os.environ.get("PATRONUS_URL", "https://patronus.labs.jb.gg")
    client = PatronusClient(token=space_token, base_url=base_url, space_client=real_client)
    yield client
    await client.aclose()


# Shared e2e constants and helpers =====================================================================================

TEST_REPO = "https://git.jetbrains.team/space-mcp/test.git"
TARGET_BRANCH = "main"

from .e2e_helpers import parse_git_url  # noqa: E402 — needed for constants below

TEST_RW_PROJECT, TEST_RW_REPO_NAME = parse_git_url(TEST_REPO)


@asynccontextmanager
async def _test_branch(token, repo_url):
    """Create a test branch with a commit, yield (project, repo, branch), delete on exit."""
    from .e2e_helpers import create_test_branch, push_test_commit, delete_branch

    project, repo_name = parse_git_url(repo_url)
    branch = f"test/{uuid.uuid4()}"
    await create_test_branch(token, repo_url, branch)
    await push_test_commit(token, repo_url, branch)
    yield project, repo_name, branch
    await delete_branch(token, repo_url, branch)


@pytest.fixture
async def test_branch_basic(space_token):
    """Create a test branch in the test repo. Deletes on teardown."""
    async with _test_branch(space_token, TEST_REPO) as result:
        yield result


@pytest.fixture
async def test_mr(real_client, test_branch_basic):
    """Create a test MR from test_branch_basic. Deletes on teardown."""
    project, repo, branch = test_branch_basic
    mr = await real_client.create_merge_request(
        project=project,
        repository=repo,
        source_branch=branch,
        target_branch=TARGET_BRANCH,
        title=f"Integration test MR ({branch})",
    )
    yield mr
    await real_client.set_merge_request_state(project, str(mr.number), "Deleted")


# Session-scoped fixtures for seeded test data =========================================================================


@pytest.fixture(scope="session")
def space_token_session():
    """Session-scoped version of space_token."""
    token = os.environ.get("SPACE_TOKEN")
    if not token:
        pytest.fail("SPACE_TOKEN not set — required for integration tests")
    return token


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def real_client_session(space_token_session):
    """Session-scoped SpaceClient."""
    client = SpaceClient(token=space_token_session)
    yield client
    await client.aclose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def real_patronus_client_session(space_token_session, real_client_session):
    """Session-scoped PatronusClient."""
    base_url = os.environ.get("PATRONUS_URL", "https://patronus.labs.jb.gg")
    client = PatronusClient(token=space_token_session, base_url=base_url, space_client=real_client_session)
    yield client
    await client.aclose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def seeded_branch(space_token_session):
    """Session-scoped test branch for seeded_mr. Deletes on teardown."""
    from .e2e_helpers import create_test_branch, push_test_commit, delete_branch

    branch = f"test/seeded-{uuid.uuid4()}"
    await create_test_branch(space_token_session, TEST_REPO, branch)
    await push_test_commit(space_token_session, TEST_REPO, branch)
    yield TEST_RW_PROJECT, TEST_RW_REPO_NAME, branch
    await delete_branch(space_token_session, TEST_REPO, branch)  # best-effort cleanup


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def seeded_mr(space_token_session, real_client_session, seeded_branch):
    """MR with rich timeline content for read-only e2e tests.

    Creates general comments, code discussions with replies, and thread replies.
    Depends on seeded_branch for branch lifecycle.
    """
    from .e2e_helpers import get_head_commit

    project, repo_name, branch = seeded_branch
    client = real_client_session
    head_sha = await get_head_commit(space_token_session, TEST_REPO, branch)

    mr = await client.create_merge_request(
        project=project,
        repository=repo_name,
        source_branch=branch,
        target_branch=TARGET_BRANCH,
        title="Seeded MR for e2e tests",
        description="MR for suppression testing and timeline verification",
    )

    # Post 3 general comments
    msg1_id = await client.post_comment(project, str(mr.number), "General comment 1")
    await client.post_comment(project, str(mr.number), "General comment 2")
    await client.post_comment(project, str(mr.number), "General comment 3")

    # Thread reply on 1st general comment
    await client.post_comment(
        project,
        str(mr.number),
        "Thread reply on comment 1",
        thread_message_id=msg1_id,
    )

    # Create 3 code discussions
    disc1_channel = await client.create_code_discussion(
        project,
        str(mr.number),
        repo_name,
        head_sha,
        "test-commit.txt",
        1,
        "Code review comment on line 1",
    )
    await client.create_code_discussion(
        project,
        str(mr.number),
        repo_name,
        head_sha,
        "test-commit.txt",
        1,
        "Code review comment #2",
    )
    await client.create_code_discussion(
        project,
        str(mr.number),
        repo_name,
        head_sha,
        "test-commit.txt",
        1,
        "Code review comment #3",
    )

    # 2 replies in 1st code discussion
    await client.reply_to_discussion(disc1_channel, "Reply to code discussion 1")
    await client.reply_to_discussion(disc1_channel, "Second reply to code discussion 1")

    yield mr
    await client.set_merge_request_state(project, str(mr.number), "Deleted")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def failed_patronus_run(real_patronus_client_session):
    """Find a failed Patronus run on test-patronus for read-only tests.

    Skips if no failed runs exist — run TestPatronusDryRun first to generate data.
    """
    runs = await real_patronus_client_session.list_runs("test-patronus")
    failed = [r for r in runs if r.status == RunStatus.FAILURE]
    if not failed:
        pytest.skip("No failed runs in test-patronus — run TestPatronusDryRun first to generate data")
    return failed[0]
