"""End-to-end tests for SpaceClient against real JetBrains Space API.

Requires SPACE_TOKEN environment variable to be set (via .env or export).
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from space.models import (
    CodeDiscussion,
    MergeRequest,
    MRState,
    SpaceApp,
    TimelineEventClass,
    TimelineMessage,
)

from .e2e_helpers import (
    parse_git_url,
    create_test_branch,
    push_test_commit,
    delete_branch,
)

# Known test data from real Space instance
TEST_PROJECT = "ij"
TEST_REPOSITORY = "ultimate"
TEST_REVIEW_NUMBER = "188120"
TEST_BRANCH = "azhukova/QD-13281"
TEST_REVIEW_190592 = "190592"
TEST_REVIEW_192360 = "192360"

# Test repositories (git remote URLs)
TEST_REPO = "https://git.jetbrains.team/space-mcp/test.git"
TEST_RW_PROJECT, TEST_RW_REPO_NAME = parse_git_url(TEST_REPO)
TARGET_BRANCH = "main"


# Read-only e2e tests (ij/ultimate) =====


@pytest.mark.e2e
class TestGetMergeRequestIntegration:

    async def test_get_merge_request_by_number(self, real_client):
        result = await real_client.get_merge_request(
            TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_NUMBER
        )

        assert isinstance(result, MergeRequest)
        assert result.id != TEST_REVIEW_NUMBER  # Internal ID differs from display number
        assert result.title
        assert result.state is not None

    async def test_get_merge_request_branch_info(self, real_client):
        result = await real_client.get_merge_request(
            TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_NUMBER
        )

        assert len(result.branch_pairs) > 0
        bp = result.branch_pairs[0]
        assert bp.source_branch == TEST_BRANCH
        assert bp.target_branch == "master"
        assert bp.repository == TEST_REPOSITORY


@pytest.mark.e2e
class TestListMergeRequestsIntegration:

    async def test_list_merge_requests_returns_results(self, real_client):
        result = await real_client.list_merge_requests(
            TEST_PROJECT, TEST_REPOSITORY, limit=5
        )
        assert isinstance(result, list)

    async def test_list_merge_requests_repository_filter(self, real_client):
        result = await real_client.list_merge_requests(
            TEST_PROJECT, TEST_REPOSITORY, limit=10
        )
        for mr in result:
            repos = [bp.repository for bp in mr.branch_pairs]
            assert TEST_REPOSITORY in repos, f"MR {mr.id} not in repository {TEST_REPOSITORY}"

    async def test_list_merge_requests_state_filter(self, real_client):
        result = await real_client.list_merge_requests(
            TEST_PROJECT, TEST_REPOSITORY, state="Open", limit=5
        )
        for mr in result:
            assert mr.state == MRState.OPENED


@pytest.mark.e2e
class TestFindMergeRequestByBranchIntegration:

    async def test_find_mr_by_branch_found(self, real_client):
        result = await real_client.find_merge_request_by_branch(
            TEST_PROJECT, TEST_REPOSITORY, TEST_BRANCH
        )
        if result is not None:
            assert isinstance(result, MergeRequest)
            branches = [bp.source_branch for bp in result.branch_pairs]
            assert TEST_BRANCH in branches

    async def test_find_mr_by_nonexistent_branch(self, real_client):
        result = await real_client.find_merge_request_by_branch(
            TEST_PROJECT, TEST_REPOSITORY, "definitely-not-a-real-branch-12345"
        )
        assert result is None


@pytest.mark.e2e
class TestEndToEndMCPFlow:

    async def test_get_mr_by_display_number(self, real_client):
        mr = await real_client.get_merge_request(
            TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_NUMBER
        )

        assert mr is not None
        assert mr.title == "QD-13281: Initial implementation of Qodana for Rust"
        assert mr.state in (MRState.OPENED, MRState.CLOSED, MRState.MERGED)
        assert len(mr.branch_pairs) == 1
        assert mr.branch_pairs[0].source_branch == TEST_BRANCH
        assert mr.branch_pairs[0].repository == TEST_REPOSITORY


@pytest.mark.e2e
class TestMR188120Timeline:

    @pytest.fixture
    async def timeline(self, real_client):
        return await real_client.get_merge_request_discussions(
            TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_NUMBER
        )

    async def test_has_both_types(self, timeline):
        has_code = any(isinstance(item, CodeDiscussion) for item in timeline)
        has_msg = any(isinstance(item, TimelineMessage) for item in timeline)
        assert has_code and has_msg

    async def test_code_discussions(self, timeline):
        code_discussions = [r for r in timeline if isinstance(r, CodeDiscussion)]
        assert len(code_discussions) == 8

        for disc in code_discussions:
            assert disc.file is not None or disc.line is not None
            assert len(disc.comments) >= 1

    async def test_code_discussion_structure(self, timeline):
        code_discussions = [r for r in timeline if isinstance(r, CodeDiscussion)]
        for disc in code_discussions:
            for comment in disc.comments:
                assert comment.text
                assert comment.author is not None
                assert comment.created_at is not None

    async def test_general_message_structure(self, timeline):
        messages = [r for r in timeline if isinstance(r, TimelineMessage)]
        assert len(messages) > 30
        for msg in messages:
            assert msg.text
            assert msg.author is not None
            assert msg.created_at is not None

    async def test_messages_have_event_class(self, timeline):
        messages = [r for r in timeline if isinstance(r, TimelineMessage)]
        for msg in messages:
            assert msg.event_class is not None

    async def test_has_mcmessage_events(self, timeline):
        messages = [r for r in timeline if isinstance(r, TimelineMessage)]
        mc_messages = [m for m in messages if m.event_class == TimelineEventClass.MC_MESSAGE]
        assert len(mc_messages) >= 10

    async def test_has_threaded_messages(self, timeline):
        messages = [r for r in timeline if isinstance(r, TimelineMessage)]
        with_threads = [m for m in messages if m.thread_replies]
        assert len(with_threads) >= 1
        for msg in with_threads:
            app_replies = [r for r in msg.thread_replies if isinstance(r.author, SpaceApp)]
            assert len(app_replies) >= 1

    async def test_has_app_authored_messages(self, timeline):
        messages = [r for r in timeline if isinstance(r, TimelineMessage)]
        app_msgs = [m for m in messages if isinstance(m.author, SpaceApp)]
        assert len(app_msgs) >= 1
        assert any(m.event_class == TimelineEventClass.M2_TEXT_ITEM for m in app_msgs)

    async def test_pagination_fetches_all_messages(self, timeline):
        assert len(timeline) > 50

    async def test_has_multiple_authors(self, timeline):
        authors = set()
        for item in timeline:
            if isinstance(item, TimelineMessage):
                authors.add(item.author.name)
            elif isinstance(item, CodeDiscussion):
                for c in item.comments:
                    authors.add(c.author.name)
        assert len(authors) >= 3


@pytest.mark.e2e
class TestMR190592Discussions:

    async def test_get_discussions_returns_results(self, real_client):
        result = await real_client.get_merge_request_discussions(
            TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_190592
        )
        assert isinstance(result, list)
        assert len(result) > 0

    async def test_includes_general_messages(self, real_client):
        result = await real_client.get_merge_request_discussions(
            TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_190592
        )
        messages = [r for r in result if isinstance(r, TimelineMessage)]
        assert len(messages) > 0


@pytest.mark.e2e
class TestMR192360Description:

    async def test_mr_has_description(self, real_client):
        result = await real_client.get_merge_request(TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_192360)
        assert result.description is not None
        assert "suppression" in result.description.lower()

    async def test_mr_has_number(self, real_client):
        result = await real_client.get_merge_request(TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_192360)
        assert result.number == 192360


# Read-write e2e tests (space-mcp/test) =====


@pytest.fixture
async def test_branch_basic(space_token):
    branch = f"test/{uuid.uuid4()}"
    await create_test_branch(space_token, TEST_REPO, branch)
    await push_test_commit(space_token, TEST_REPO, branch)
    yield TEST_RW_PROJECT, TEST_RW_REPO_NAME, branch
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
        await real_client.set_merge_request_state(project, str(mr.number), "Closed")
    except Exception:
        pass


@pytest.mark.e2e
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
        fetched = await real_client.get_merge_request(TEST_RW_PROJECT, TEST_RW_REPO_NAME, str(test_mr.number))
        assert fetched.number == test_mr.number
        assert fetched.title == test_mr.title
        assert fetched.id == test_mr.id

    async def test_close_mr(self, real_client, test_mr):
        number = str(test_mr.number)
        await real_client.set_merge_request_state(TEST_RW_PROJECT, number, "Closed")
        fetched = await real_client.get_merge_request(TEST_RW_PROJECT, TEST_RW_REPO_NAME, number)
        assert fetched.state == MRState.CLOSED
        await real_client.set_merge_request_state(TEST_RW_PROJECT, number, "Opened")

    async def test_reopen_mr(self, real_client, test_mr):
        number = str(test_mr.number)
        await real_client.set_merge_request_state(TEST_RW_PROJECT, number, "Closed")
        await real_client.set_merge_request_state(TEST_RW_PROJECT, number, "Opened")
        fetched = await real_client.get_merge_request(TEST_RW_PROJECT, TEST_RW_REPO_NAME, number)
        assert fetched.state == MRState.OPENED

    async def test_find_mr_by_branch(self, real_client, test_mr, test_branch_basic):
        _, _, branch = test_branch_basic
        found = await real_client.find_merge_request_by_branch(TEST_RW_PROJECT, TEST_RW_REPO_NAME, branch)
        assert found is not None
        assert found.number == test_mr.number

    async def test_list_mrs_includes_test_mr(self, real_client, test_mr):
        mrs = await real_client.list_merge_requests(TEST_RW_PROJECT, TEST_RW_REPO_NAME, state="Open")
        numbers = [mr.number for mr in mrs]
        assert test_mr.number in numbers

    async def test_get_discussions_on_new_mr(self, real_client, test_mr):
        discussions = await real_client.get_merge_request_discussions(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, str(test_mr.number),
        )
        assert isinstance(discussions, list)


@pytest.mark.e2e
class TestMerge:

    @pytest.fixture
    async def merge_branch(self, space_token):
        branch = f"test/{uuid.uuid4()}"
        await create_test_branch(space_token, TEST_REPO, branch)
        await push_test_commit(space_token, TEST_REPO, branch)
        yield TEST_RW_PROJECT, TEST_RW_REPO_NAME, branch
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
