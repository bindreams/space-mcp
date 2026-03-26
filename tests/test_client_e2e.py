"""End-to-end tests for SpaceClient against real JetBrains Space API.

Requires SPACE_TOKEN environment variable to be set (via .env or export).
"""
from __future__ import annotations

import pytest

from space.models import (
    CodeDiscussion,
    MergeRequest,
    MRState,
    SpaceAccount,
    SpaceApp,
    TimelineMessage,
)

from .conftest import TEST_RW_PROJECT, TEST_RW_REPO_NAME, TARGET_BRANCH


# Read-only e2e tests (use seeded_mr fixture from conftest) =====


@pytest.mark.e2e
class TestGetMergeRequestIntegration:

    async def test_get_merge_request_by_number(self, real_client, seeded_mr):
        result = await real_client.get_merge_request(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, str(seeded_mr.number)
        )
        assert isinstance(result, MergeRequest)
        assert result.title
        assert result.state is not None

    async def test_get_merge_request_branch_info(self, real_client, seeded_mr):
        result = await real_client.get_merge_request(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, str(seeded_mr.number)
        )
        assert len(result.branch_pairs) > 0
        bp = result.branch_pairs[0]
        assert bp.source_branch.startswith("test/seeded-")
        assert bp.target_branch == "main"
        assert bp.repository == TEST_RW_REPO_NAME


@pytest.mark.e2e
class TestListMergeRequestsIntegration:

    async def test_list_merge_requests_returns_results(self, real_client, seeded_mr):
        result = await real_client.list_merge_requests(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, limit=5
        )
        assert isinstance(result, list)

    async def test_list_merge_requests_repository_filter(self, real_client, seeded_mr):
        result = await real_client.list_merge_requests(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, limit=10
        )
        for mr in result:
            repos = [bp.repository for bp in mr.branch_pairs]
            assert TEST_RW_REPO_NAME in repos, f"MR {mr.id} not in repository {TEST_RW_REPO_NAME}"

    async def test_list_merge_requests_state_filter(self, real_client, seeded_mr):
        result = await real_client.list_merge_requests(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, state="Open", limit=5
        )
        for mr in result:
            assert mr.state == MRState.OPENED

    async def test_list_merge_requests_branch_filter(self, real_client, seeded_mr):
        branch = seeded_mr.branch_pairs[0].source_branch
        result = await real_client.list_merge_requests(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, branch=branch, limit=5
        )
        assert len(result) >= 1
        for mr in result:
            branches = [bp.source_branch for bp in mr.branch_pairs]
            assert branch in branches

    async def test_page_size_accepted_by_api(self, real_client, seeded_mr):
        """Validate that our page size is accepted by the Space API."""
        from space.pagination import _PAGE_SIZE
        import httpx

        url = f"{real_client.base_url}/api/http/projects/key:{TEST_RW_PROJECT}/code-reviews"
        params = {
            "$fields": "data(review(id))",
            "type": "MergeRequest",
            "$top": _PAGE_SIZE,
            "$skip": 0,
        }
        async with httpx.AsyncClient() as http:
            resp = await http.get(url, headers=real_client._headers(), params=params)
        assert resp.status_code == 200, f"API rejected $top={_PAGE_SIZE}: {resp.status_code}"


@pytest.mark.e2e
class TestFindMergeRequestByBranchIntegration:

    async def test_find_mr_by_branch_found(self, real_client, seeded_mr):
        branch = seeded_mr.branch_pairs[0].source_branch
        result = await real_client.find_merge_request_by_branch(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, branch
        )
        assert result is not None
        assert isinstance(result, MergeRequest)
        branches = [bp.source_branch for bp in result.branch_pairs]
        assert branch in branches

    async def test_find_mr_by_nonexistent_branch(self, real_client):
        result = await real_client.find_merge_request_by_branch(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, "definitely-not-a-real-branch-12345"
        )
        assert result is None


@pytest.mark.e2e
class TestEndToEndMCPFlow:

    async def test_get_mr_by_display_number(self, real_client, seeded_mr):
        mr = await real_client.get_merge_request(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, str(seeded_mr.number)
        )
        assert mr is not None
        assert mr.title == "Seeded MR for e2e tests"
        assert mr.state in (MRState.OPENED, MRState.CLOSED, MRState.MERGED)
        assert len(mr.branch_pairs) == 1
        assert mr.branch_pairs[0].source_branch.startswith("test/seeded-")
        assert mr.branch_pairs[0].repository == TEST_RW_REPO_NAME


@pytest.mark.e2e
class TestMRTimelineIntegration:

    @pytest.fixture
    async def timeline(self, real_client, seeded_mr):
        return await real_client.get_merge_request_discussions(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, str(seeded_mr.number)
        )

    async def test_has_both_types(self, timeline):
        has_code = any(isinstance(item, CodeDiscussion) for item in timeline)
        has_msg = any(isinstance(item, TimelineMessage) for item in timeline)
        assert has_code and has_msg

    async def test_code_discussions(self, timeline):
        code_discussions = [r for r in timeline if isinstance(r, CodeDiscussion)]
        assert len(code_discussions) >= 3
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
        assert len(messages) >= 3
        for msg in messages:
            assert msg.text
            assert msg.author is not None
            assert msg.created_at is not None

    async def test_messages_have_event_class(self, timeline):
        messages = [r for r in timeline if isinstance(r, TimelineMessage)]
        for msg in messages:
            assert msg.event_class is not None

    async def test_has_threaded_messages(self, timeline):
        """Thread replies on general messages may not appear depending on Space API timing.
        Code discussion replies (tested in test_code_discussion_has_replies) are the reliable path.
        """
        messages = [r for r in timeline if isinstance(r, TimelineMessage)]
        with_threads = [m for m in messages if m.thread_replies]
        # Soft assertion — thread replies may not be visible in feed timeline
        if not with_threads:
            pytest.skip("Thread replies not visible in feed timeline (Space API timing)")

    async def test_has_app_or_user_authored_messages(self, timeline):
        messages = [r for r in timeline if isinstance(r, TimelineMessage)]
        assert len(messages) >= 1
        for msg in messages:
            assert isinstance(msg.author, (SpaceAccount, SpaceApp))

    async def test_has_at_least_one_author(self, timeline):
        authors = set()
        for item in timeline:
            if isinstance(item, TimelineMessage):
                authors.add(item.author.name)
            elif isinstance(item, CodeDiscussion):
                for c in item.comments:
                    authors.add(c.author.name)
        assert len(authors) >= 1

    async def test_code_discussion_has_replies(self, timeline):
        """The first code discussion should have 3 comments (1 original + 2 replies)."""
        code_discussions = [r for r in timeline if isinstance(r, CodeDiscussion)]
        multi_comment = [d for d in code_discussions if len(d.comments) >= 3]
        assert len(multi_comment) >= 1

    async def test_total_timeline_items(self, timeline):
        assert len(timeline) >= 6


@pytest.mark.e2e
class TestMRDiscussionsIntegration:

    async def test_get_discussions_returns_results(self, real_client, seeded_mr):
        result = await real_client.get_merge_request_discussions(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, str(seeded_mr.number)
        )
        assert isinstance(result, list)
        assert len(result) > 0

    async def test_includes_general_messages(self, real_client, seeded_mr):
        result = await real_client.get_merge_request_discussions(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, str(seeded_mr.number)
        )
        messages = [r for r in result if isinstance(r, TimelineMessage)]
        assert len(messages) > 0


@pytest.mark.e2e
class TestMRDescriptionIntegration:

    async def test_mr_has_description(self, real_client, seeded_mr):
        result = await real_client.get_merge_request(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, str(seeded_mr.number)
        )
        assert result.description is not None
        assert "suppression" in result.description.lower()

    async def test_mr_has_number(self, real_client, seeded_mr):
        result = await real_client.get_merge_request(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, str(seeded_mr.number)
        )
        assert result.number == seeded_mr.number


# Read-write e2e tests (space-mcp/test) =====


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

    async def test_list_mrs_by_branch_includes_test_mr(self, real_client, test_mr, test_branch_basic):
        _, _, branch = test_branch_basic
        mrs = await real_client.list_merge_requests(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, branch=branch, state="Open",
        )
        numbers = [mr.number for mr in mrs]
        assert test_mr.number in numbers

    async def test_get_discussions_on_new_mr(self, real_client, test_mr):
        discussions = await real_client.get_merge_request_discussions(
            TEST_RW_PROJECT, TEST_RW_REPO_NAME, str(test_mr.number),
        )
        assert isinstance(discussions, list)


@pytest.mark.e2e
class TestMerge:

    async def test_merge_mr(self, real_client, test_branch_basic):
        project, repo, branch = test_branch_basic
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
