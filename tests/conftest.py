import copy
import os
import uuid

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


# SpaceAccount cache management =====


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
        SpaceAccount(id="user-azhukova", username="azhukova", email="anna@test.com", first_name="Anna", last_name="Zhukova"),
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


# Fixtures for unit tests (fake base URL, no real API calls) =====


@pytest.fixture
def space_client():
    """Create a SpaceClient instance with test token."""
    return SpaceClient(token="test-token")


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


# Patronus fixtures =====


@pytest.fixture
def patronus_client(space_client):
    """Create a PatronusClient instance with test token and SpaceClient."""
    return PatronusClient(token="test-token", space_client=space_client)


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


# Fixtures for integration tests (real API calls, loaded from .env) =====


@pytest.fixture
def space_token():
    """Get SPACE_TOKEN from environment (loaded from .env by pytest-dotenv).

    Fails (not skips) if missing — a missing token is a CI configuration problem.
    """
    token = os.environ.get("SPACE_TOKEN")
    if not token:
        pytest.fail("SPACE_TOKEN not set — required for integration tests")
    return token


@pytest.fixture
def real_client(space_token):
    """Create a SpaceClient with real token for integration tests."""
    return SpaceClient(token=space_token)


@pytest.fixture
def real_patronus_client(space_token, real_client):
    """Create a PatronusClient with real token for integration tests."""
    base_url = os.environ.get("PATRONUS_URL", "https://patronus.labs.jb.gg")
    return PatronusClient(token=space_token, base_url=base_url, space_client=real_client)


# Session-scoped fixtures for seeded test data =====


_SEEDED_MR_REPO = "https://git.jetbrains.team/space-mcp/test.git"


@pytest.fixture(scope="session")
def space_token_session():
    """Session-scoped version of space_token."""
    token = os.environ.get("SPACE_TOKEN")
    if not token:
        pytest.fail("SPACE_TOKEN not set — required for integration tests")
    return token


@pytest.fixture(scope="session")
def real_client_session(space_token_session):
    """Session-scoped SpaceClient."""
    return SpaceClient(token=space_token_session)


@pytest.fixture(scope="session")
def real_patronus_client_session(space_token_session, real_client_session):
    """Session-scoped PatronusClient."""
    base_url = os.environ.get("PATRONUS_URL", "https://patronus.labs.jb.gg")
    return PatronusClient(token=space_token_session, base_url=base_url, space_client=real_client_session)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def seeded_mr(space_token_session, real_client_session):
    """Create an MR with rich timeline content for read-only e2e tests.

    Creates general comments, code discussions with replies, and thread replies.
    Cleaned up automatically after the test session.
    """
    from .e2e_helpers import (
        parse_git_url, create_test_branch, push_test_commit,
        delete_branch, get_head_commit,
    )

    project, repo_name = parse_git_url(_SEEDED_MR_REPO)
    token = space_token_session
    client = real_client_session
    branch = f"test/seeded-{uuid.uuid4()}"
    mr = None

    try:
        # Create branch with a test commit
        await create_test_branch(token, _SEEDED_MR_REPO, branch)
        await push_test_commit(token, _SEEDED_MR_REPO, branch)
        head_sha = await get_head_commit(token, _SEEDED_MR_REPO, branch)

        # Create MR
        mr = await client.create_merge_request(
            project=project, repository=repo_name,
            source_branch=branch, target_branch="main",
            title="Seeded MR for e2e tests",
            description="MR for suppression testing and timeline verification",
        )

        # Post 3 general comments
        msg1_id = await client.post_comment(project, str(mr.number), "General comment 1")
        await client.post_comment(project, str(mr.number), "General comment 2")
        await client.post_comment(project, str(mr.number), "General comment 3")

        # Thread reply on 1st general comment
        await client.post_comment(
            project, str(mr.number), "Thread reply on comment 1",
            thread_message_id=msg1_id,
        )

        # Create 3 code discussions
        disc1_channel = await client.create_code_discussion(
            project, str(mr.number), repo_name, head_sha,
            "test-commit.txt", 1, "Code review comment on line 1",
        )
        await client.create_code_discussion(
            project, str(mr.number), repo_name, head_sha,
            "test-commit.txt", 1, "Code review comment #2",
        )
        await client.create_code_discussion(
            project, str(mr.number), repo_name, head_sha,
            "test-commit.txt", 1, "Code review comment #3",
        )

        # 2 replies in 1st code discussion
        await client.reply_to_discussion(disc1_channel, "Reply to code discussion 1")
        await client.reply_to_discussion(disc1_channel, "Second reply to code discussion 1")

        yield mr
    finally:
        if mr:
            try:
                await client.set_merge_request_state(project, str(mr.number), "Deleted")
            except Exception:
                pass
        try:
            await delete_branch(token, _SEEDED_MR_REPO, branch)
        except Exception:
            pass


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
