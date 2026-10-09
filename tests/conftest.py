import copy
import os
import sys
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio

from . import _status_guard  # isort: skip -- installs the guard before any `space.*` import below
from space.client import SpaceClient
from space.models import SpaceAccount, enums
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


# Unrecognised Patronus status guard ===================================================================================

_UNRECOGNISED_MARKER = "unrecognised_patronus_status"

_ITEM_PHASES = ("setup", "call", "teardown")

_STATE: pytest.StashKey[_status_guard.GuardState] = pytest.StashKey()


def _describe(records: list[_status_guard.Record]) -> str:
    return ", ".join(f"{name} {value} ({phase})" for name, value, phase in records)


def pytest_configure(config):
    """Claim the guard state, which already holds the values parsed while importing the test modules.

    The rule: `@pytest.mark.unrecognised_patronus_status` permits unrecognised values only in the call phase of the
    marked test. A value parsed in any other phase (setup or teardown of a fixture of any scope, including one
    requested with `request.getfixturevalue`; collection; or between items) fails the run regardless of markers:
    fixtures must not parse unrecognised values. Limitation: `unittest.TestCase.setUp` runs inside pytest's call
    phase and cannot be told apart from the test body.
    """
    config.stash[_STATE] = _status_guard.claim()


def pytest_unconfigure(config):
    state = config.stash.get(_STATE, None)
    if state is not None:  # absent when an earlier `pytest_configure` failed before ours ran
        _status_guard.release(state)


def pytest_collection_finish(session):
    state = session.config.stash[_STATE]
    state.phase = "between"
    collected = [r for r in state.records if r[2] == "collection"]
    if collected:
        raise pytest.UsageError(f"parsed a value Patronus does not send while collecting: {_describe(collected)}")


def _enter(item, phase: str) -> _status_guard.GuardState:
    state = item.config.stash[_STATE]
    state.phase = phase
    return state


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(fixturedef, request):
    """A fixture set up late (`request.getfixturevalue` in a test body) is still fixture code."""
    state = request.config.stash[_STATE]
    previous, state.phase = state.phase, "setup"
    try:
        return (yield)
    finally:
        state.phase = previous


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_setup(item):
    """Mark where this item's records begin; reset per item so each test re-logs values already seen."""
    state = _enter(item, "setup")
    state.item_start = len(state.records)
    state.current_item = item
    state.item_checked = False
    enums._logged_unrecognised.clear()
    try:
        return (yield)
    finally:
        state.phase = "between"


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_call(item):
    state = _enter(item, "call")
    try:
        return (yield)
    finally:
        state.phase = "between"


def _item_message(state: _status_guard.GuardState, item) -> str | None:
    """The violations among the item's records so far, as a message; the marker permits call-phase values."""
    marked = item.get_closest_marker(_UNRECOGNISED_MARKER) is not None
    violations = [
        r for r in state.records[state.item_start:] if r[2] in _ITEM_PHASES and (r[2] != "call" or not marked)
    ]
    if not violations:
        return None
    return (
        f"parsed a value Patronus does not send: {_describe(violations)}; use wire values, or parse it in the body "
        f"of a test marked @pytest.mark.{_UNRECOGNISED_MARKER}"
    )


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_teardown(item):
    """Record the item's violations, even when a teardown raises.

    Module-, class- and session-scoped fixtures run inside the setup/teardown of some item, so their parses are
    checked here too (the last item of the run finalises the session fixtures). The failure itself is raised by
    `pytest_runtest_makereport`, which xfail cannot turn into an expected failure.
    """
    state = _enter(item, "teardown")
    try:
        return (yield)
    finally:
        state.phase = "between"
        state.item_checked = True
        message = _item_message(state, item)
        if message is not None:
            state.item_violations[item.nodeid] = message
            state.session_messages.append(f"{item.nodeid}: {message}")


_REPORT_SECTION = "unrecognised Patronus statuses"


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    report = yield
    message = item.config.stash[_STATE].item_violations.get(item.nodeid)
    if call.when == "teardown" and message is not None:
        report.outcome = "failed"
        if hasattr(report, "wasxfail"):
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
    return report


def _session_messages(state: _status_guard.GuardState) -> list[str]:
    """Everything the item checks could not report: leftovers of a cut-short run and records between items."""
    messages = list(state.session_messages)
    collected = [r for r in state.records if r[2] == "collection"]
    if collected:
        messages.append(f"parsed a value Patronus does not send while collecting: {_describe(collected)}")
    if state.current_item is not None and not state.item_checked:
        message = _item_message(state, state.current_item)
        if message is not None:
            messages.append(f"{state.current_item.nodeid}: {message}")
    between = [r for r in state.records if r[2] == "between"]
    if between:
        messages.append(f"parsed a value Patronus does not send between tests: {_describe(between)}")
    return messages


def _fail_session(session, messages: list[str]) -> None:
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    text = "\n".join(messages)
    if reporter is not None:
        reporter.ensure_newline()
        reporter.write_line(text, red=True)
    else:
        print(text, file=sys.stderr)
    if session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def _check_session(session) -> None:
    """Report and fail on `_session_messages`; turn an in-flight `pytest.exit(returncode=0)` into a failure."""
    messages = _session_messages(session.config.stash[_STATE])
    if not messages:
        return
    _fail_session(session, messages)
    in_flight = sys.exc_info()[1]
    if isinstance(in_flight, pytest.exit.Exception) and in_flight.returncode == 0:
        # wrap_session takes the exit status from the exception
        raise pytest.exit.Exception(in_flight.msg, returncode=pytest.ExitCode.TESTS_FAILED) from in_flight


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_sessionstart(session):
    """When a start hook aborts the run, `pytest_sessionfinish` never runs, so check here."""
    try:
        return (yield)
    except BaseException:
        _check_session(session)
        raise


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_sessionfinish(session):
    """Fail the session for violations the item reports could not carry, even if another finish hook raises.

    Checked after the other `pytest_sessionfinish` hooks: `pytest.exit` finalises session fixtures there.
    """
    try:
        return (yield)
    finally:
        _check_session(session)


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
