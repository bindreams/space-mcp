import copy
import os
import sys
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from hypothesis import HealthCheck, settings

from space.models import enums  # isort: skip -- strict before anything below parses at import time

_STRICT_AT_IMPORT = enums._strict
# the strict rejections recorded since the last report; drained by the hooks below
_VIOLATIONS_AT_IMPORT = enums._set_violation_record([])
enums.set_strict(True)

from space.client import SpaceClient
from space.models import SpaceAccount
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

# Hypothesis's deadline and too_slow check are wall-clock assertions, flaky on loaded CI.
settings.register_profile("space", deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.load_profile("space")

# Git credential isolation =============================================================================================


@pytest.fixture(autouse=True, scope="session")
def _isolate_git_credentials():
    """Prevent git subprocesses from reading or writing system credentials.

    Without this, any git command that uses an authenticated URL
    (https://:token@host/...) will store the token in the OS keychain
    via the system credential helper, polluting the user's real credentials.
    """
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    os.environ["GIT_CONFIG_GLOBAL"] = "/dev/null"
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    yield
    os.environ.pop("GIT_CONFIG_NOSYSTEM", None)
    os.environ.pop("GIT_CONFIG_GLOBAL", None)
    os.environ.pop("GIT_TERMINAL_PROMPT", None)


# Strict mode ==========================================================================================================

_PERMISSIVE_MARKER = "unrecognised_api_value"
_EXPECTS_RAISE_MARKER = "raises_unrecognised_api_value"

_SPACE_STRICT_BEFORE: pytest.StashKey[str | None] = pytest.StashKey()

# Violations recorded while a fixture was set up; never allowed, whatever the test's markers.
_fixture_violations: list[tuple[str, str]] = []

_REPORT_SECTION = "strict mode"


def _strict_on() -> None:
    enums.set_strict(True)


def _take(violations: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Drain a list only the pytest hooks touch; the enum record goes through `enums._drain_violations`."""
    taken = list(violations)
    violations.clear()
    return taken


def _describe(violations: list[tuple[str, str]], phase: str) -> str:
    found = ", ".join(f"{name} {value} ({phase})" for name, value in violations)
    return (
        f"strict mode rejected an unmodelled API value: {found}; use a wire value, mark the test "
        f"@pytest.mark.{_PERMISSIVE_MARKER}, or, if it expects the raise, @pytest.mark.{_EXPECTS_RAISE_MARKER}"
    )


class _FixtureBoundaries:
    """Fixture hooks, registered as a plugin by `pytest_configure`.

    Defined in this conftest they would never see session-scoped fixtures: pytest dispatches those through the
    Session's path-scoped hook proxy, which leaves out conftests below the rootdir.
    """

    @pytest.hookimpl(wrapper=True)
    def pytest_fixture_setup(self, fixturedef, request):
        """Every fixture sets up strict, even one requested from the body of a permissive test."""
        before = enums._strict
        enums.set_strict(True)
        start = enums._violation_count()
        try:
            return (yield)
        finally:
            # runs just before the fixture's own teardown, which a body finalizer may have left permissive
            fixturedef.addfinalizer(_strict_on)
            _fixture_violations.extend(enums._drain_violations(start))
            enums.set_strict(before)

    def pytest_fixture_post_finalizer(self, fixturedef, request):
        enums.set_strict(True)


def pytest_configure(config):
    """Strict everywhere except the body of a test marked `unrecognised_api_value`.

    The switch never carries from one fixture, test body or phase into another; code that turns strict off itself
    owns that choice until the next boundary. A strict rejection fails the test even when the code under test caught
    it, unless the test is marked `raises_unrecognised_api_value` and the rejection happened in its body.
    Limitation: `unittest.TestCase.setUp` runs in the call phase.
    """
    enums.set_strict(True)
    config.stash[_SPACE_STRICT_BEFORE] = os.environ.get("SPACE_STRICT")
    # after pytest-dotenv's `pytest_load_initial_conftests`, so it beats `.env` and the developer's shell
    os.environ["SPACE_STRICT"] = "1"
    config.pluginmanager.register(_FixtureBoundaries(), "space-strict-fixture-boundaries")


def pytest_unconfigure(config):
    plugin = config.pluginmanager.get_plugin("space-strict-fixture-boundaries")
    if plugin is not None:
        config.pluginmanager.unregister(plugin)
    if _SPACE_STRICT_BEFORE in config.stash:
        before = config.stash[_SPACE_STRICT_BEFORE]
        if before is None:
            os.environ.pop("SPACE_STRICT", None)
        else:
            os.environ["SPACE_STRICT"] = before
    enums.set_strict(_STRICT_AT_IMPORT)
    enums._set_violation_record(_VIOLATIONS_AT_IMPORT)


def pytest_collection_finish(session):
    collected = enums._drain_violations() + _take(_fixture_violations)
    if collected:
        raise pytest.UsageError(_describe(collected, "collection"))


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_setup(item):
    enums.set_strict(True)
    enums._logged_unrecognised.clear()
    return (yield)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_call(item):
    """The marker is read before the body runs, so `request.applymarker` in a body has no effect."""
    enums.set_strict(item.get_closest_marker(_PERMISSIVE_MARKER) is None)
    try:
        return (yield)
    finally:
        enums.set_strict(True)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    enums.set_strict(True)
    return (yield)


def _fail_report(report, message: str) -> None:
    report.outcome = "failed"
    if hasattr(report, "wasxfail"):  # xfail must not hide a rejection
        del report.wasxfail
    longrepr = report.longrepr
    if longrepr is None:
        report.longrepr = message
    elif isinstance(longrepr, str):
        report.longrepr = f"{message}\n\n{longrepr}"
    elif isinstance(longrepr, tuple):  # a skip: (path, lineno, reason)
        report.longrepr = f"{longrepr[2]}\n\n{message}"
    elif hasattr(longrepr, "addsection"):  # keeps the exception's own repr, so summaries show its message
        longrepr.addsection(_REPORT_SECTION, message)
    else:
        report.longrepr = f"{longrepr}\n\n{message}"


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    report = yield
    direct = enums._drain_violations()
    if call.when == "call" and item.get_closest_marker(_EXPECTS_RAISE_MARKER) is not None:
        direct = []
    violations = direct + _take(_fixture_violations)
    if violations:
        _fail_report(report, _describe(violations, call.when))
    return report


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_sessionfinish(session):
    """Rejections recorded outside every item's phases fail the session."""
    try:
        return (yield)
    finally:
        leftovers = enums._drain_violations() + _take(_fixture_violations)
        if leftovers:
            message = _describe(leftovers, "outside any test")
            reporter = session.config.pluginmanager.get_plugin("terminalreporter")
            if reporter is not None:
                reporter.ensure_newline()
                reporter.write_line(message, red=True)
            else:
                print(message, file=sys.stderr)
            if session.exitstatus == pytest.ExitCode.OK:
                session.exitstatus = pytest.ExitCode.TESTS_FAILED


# Settings isolation ===================================================================================================


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch, tmp_path):
    """Keep the developer's `SPACE_STRICT` and config file out of every test; tests that need others set their own."""
    monkeypatch.setenv("SPACE_STRICT", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


# HTTP isolation =======================================================================================================

# Fixtures that talk to the real Space/Patronus APIs with the token from .env; only e2e tests may request them.
_REAL_NETWORK_FIXTURES = frozenset({
    "space_token",
    "space_token_session",
    "real_client",
    "real_client_session",
    "real_patronus_client",
    "real_patronus_client_session",
    "seeded_branch",
    "seeded_mr",
    "seeded_patronus_run",
    "completed_failed_run",
    "patronus_repo_ready",
})


@pytest.fixture(autouse=True)
def _block_unmocked_http(request):
    """Fail any non-e2e test that sends an httpx request it did not mock.

    Covers the test and its function-scoped fixtures. Wider-scoped fixtures run before the transports are patched,
    so a non-e2e test must not request the real-network fixtures above (enforced here) and new module-, class- or
    session-scoped fixtures in non-e2e tests must not make HTTP requests (not enforced).
    """
    if request.node.get_closest_marker("e2e") is not None:
        return
    real = sorted(_REAL_NETWORK_FIXTURES.intersection(request.fixturenames))
    if real:
        pytest.fail(f"non-e2e test requests real-network fixtures {real}; mark it e2e or mock the API", pytrace=False)
    request.getfixturevalue("httpx_mock")


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
    from .e2e_helpers import require_env_token

    return require_env_token("SPACE_TOKEN")


@pytest_asyncio.fixture
async def real_client(space_token):
    """Create a SpaceClient with real token for integration tests."""
    client = SpaceClient(token=space_token)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def real_patronus_client(space_token, real_client):
    """Create a PatronusClient with real token for integration tests."""
    from .e2e_helpers import staging_patronus_url

    base_url = staging_patronus_url()
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
    from .e2e_helpers import require_env_token

    return require_env_token("SPACE_TOKEN")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def real_client_session(space_token_session):
    """Session-scoped SpaceClient."""
    client = SpaceClient(token=space_token_session)
    yield client
    await client.aclose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def real_patronus_client_session(space_token_session, real_client_session):
    """Session-scoped PatronusClient."""
    from .e2e_helpers import staging_patronus_url

    base_url = staging_patronus_url()
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
