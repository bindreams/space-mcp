"""Integration tests for Space MCP client using real JetBrains Space API.

These tests require SPACE_TOKEN environment variable to be set.
They use a known MR (188120) in the ij/ultimate repository.
"""
import os

import pytest

from space_mcp.client import SpaceClient


# Skip all tests if no token is available
pytestmark = pytest.mark.skipif(
    not os.environ.get("SPACE_TOKEN"),
    reason="SPACE_TOKEN environment variable not set"
)

# Known test data from real Space instance
TEST_PROJECT = "ij"
TEST_REPOSITORY = "ultimate"
TEST_REVIEW_NUMBER = "188120"  # Display number from URL
TEST_BRANCH = "azhukova/QD-13281"


@pytest.fixture
def real_client():
    """Create a SpaceClient with real token."""
    token = os.environ.get("SPACE_TOKEN")
    return SpaceClient(token)


class TestGetMergeRequestIntegration:
    """Integration tests for get_merge_request."""

    async def test_get_merge_request_by_number(self, real_client):
        """Test fetching MR by display number."""
        result = await real_client.get_merge_request(
            TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_NUMBER
        )

        assert result is not None
        assert "id" in result  # Internal ID should be present
        assert result.get("id") != TEST_REVIEW_NUMBER  # Internal ID differs from display number
        assert "title" in result
        assert "state" in result
        assert "branchPairs" in result

    async def test_get_merge_request_branch_info(self, real_client):
        """Test that branch info is correctly returned."""
        result = await real_client.get_merge_request(
            TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_NUMBER
        )

        branch_pairs = result.get("branchPairs", [])
        assert len(branch_pairs) > 0

        bp = branch_pairs[0]
        assert bp.get("sourceBranch") == TEST_BRANCH
        assert bp.get("targetBranch") == "master"
        # Repository should be a string (when using repository(name) in $fields)
        assert bp.get("repository") == TEST_REPOSITORY


class TestListMergeRequestsIntegration:
    """Integration tests for list_merge_requests."""

    async def test_list_merge_requests_returns_results(self, real_client):
        """Test that listing MRs returns results."""
        result = await real_client.list_merge_requests(
            TEST_PROJECT, TEST_REPOSITORY, limit=5
        )

        # Should return a list (may be empty if no MRs in repo)
        assert isinstance(result, list)

    async def test_list_merge_requests_repository_filter(self, real_client):
        """Test that repository filtering works correctly."""
        result = await real_client.list_merge_requests(
            TEST_PROJECT, TEST_REPOSITORY, limit=10
        )

        # All returned MRs should be in the specified repository
        for review in result:
            branch_pairs = review.get("branchPairs", [])
            repos = [bp.get("repository") for bp in branch_pairs]
            # At least one branch pair should match the repository
            # (repository might be string or object with 'name')
            matching = any(
                r == TEST_REPOSITORY or (isinstance(r, dict) and r.get("name") == TEST_REPOSITORY)
                for r in repos
            )
            assert matching, f"MR {review.get('id')} not in repository {TEST_REPOSITORY}"

    async def test_list_merge_requests_state_filter(self, real_client):
        """Test filtering by state."""
        result = await real_client.list_merge_requests(
            TEST_PROJECT, TEST_REPOSITORY, state="Open", limit=5
        )

        # All returned MRs should be in Open/Opened state
        for review in result:
            assert review.get("state") in ("Open", "Opened")


class TestFindMergeRequestByBranchIntegration:
    """Integration tests for find_merge_request_by_branch."""

    async def test_find_mr_by_branch_found(self, real_client):
        """Test finding MR by branch name."""
        result = await real_client.find_merge_request_by_branch(
            TEST_PROJECT, TEST_REPOSITORY, TEST_BRANCH
        )

        # This may be None if MR is closed/merged
        if result is not None:
            assert "title" in result
            # Verify it's the right MR
            branch_pairs = result.get("branchPairs", [])
            branches = [bp.get("sourceBranch") for bp in branch_pairs]
            assert TEST_BRANCH in branches

    async def test_find_mr_by_nonexistent_branch(self, real_client):
        """Test that nonexistent branch returns None."""
        result = await real_client.find_merge_request_by_branch(
            TEST_PROJECT, TEST_REPOSITORY, "definitely-not-a-real-branch-12345"
        )

        assert result is None


class TestTextSearchIntegration:
    """Integration tests for server-side text search."""

    async def test_text_search_finds_mr_by_branch(self, real_client):
        """Test that text search finds MR when searching by branch name."""
        # This is exactly what find_merge_request_by_branch does internally
        reviews = await real_client.list_merge_requests(
            project=TEST_PROJECT,
            repository=TEST_REPOSITORY,
            branch=TEST_BRANCH,
            state="Open",
            limit=50,
            text=TEST_BRANCH,
        )

        # Should find exactly our target MR
        assert len(reviews) >= 1, f"Expected to find MR with branch {TEST_BRANCH}"

        # Verify the target MR is in results
        found = False
        for review in reviews:
            for bp in review.get("branchPairs", []):
                if bp.get("sourceBranch") == TEST_BRANCH:
                    found = True
                    break
        assert found, f"Target branch {TEST_BRANCH} not found in results"

    async def test_text_search_with_issue_id(self, real_client):
        """Test text search using issue ID from branch name."""
        # Search by just the issue ID part
        reviews = await real_client.list_merge_requests(
            project=TEST_PROJECT,
            repository=None,  # Don't filter by repo
            state="Open",
            limit=20,
            text="QD-13281",
        )

        assert len(reviews) >= 1, "Expected to find MR with QD-13281 in title/branch"


class TestEndToEndMCPFlow:
    """End-to-end tests that mirror exact MCP tool call flows."""

    async def test_find_mr_then_get_details(self, real_client):
        """Test the complete flow: find MR by branch, then get full details."""
        # Step 1: Find MR by branch (what find_merge_request_by_branch does)
        mr = await real_client.find_merge_request_by_branch(
            TEST_PROJECT, TEST_REPOSITORY, TEST_BRANCH
        )

        assert mr is not None, f"Failed to find MR for branch {TEST_BRANCH}"
        assert "id" in mr
        assert "title" in mr
        assert "QD-13281" in mr.get("title", "")

    async def test_get_mr_by_display_number(self, real_client):
        """Test getting MR by the display number from URL."""
        # This is what users typically have - the number from the URL
        mr = await real_client.get_merge_request(
            TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_NUMBER
        )

        assert mr is not None
        assert mr.get("title") == "QD-13281: Initial implementation of Qodana for Rust"
        assert mr.get("state") == "Opened"

        # Verify branch info
        branch_pairs = mr.get("branchPairs", [])
        assert len(branch_pairs) == 1
        assert branch_pairs[0].get("sourceBranch") == TEST_BRANCH
        assert branch_pairs[0].get("repository") == TEST_REPOSITORY


class TestGetMergeRequestDiscussionsIntegration:
    """Integration tests for get_merge_request_discussions."""

    async def test_get_discussions_by_number(self, real_client):
        """Test fetching discussions by display number."""
        result = await real_client.get_merge_request_discussions(
            TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_NUMBER
        )

        # Should return a list of code discussions
        assert isinstance(result, list)
        # The test MR has discussions according to discussionCounter
        assert len(result) > 0, "Expected MR to have some discussions"

    async def test_discussions_structure(self, real_client):
        """Test that discussions have expected structure."""
        result = await real_client.get_merge_request_discussions(
            TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_NUMBER
        )

        for discussion in result:
            # Each discussion should have these fields
            assert "id" in discussion
            assert "file" in discussion
            assert "line" in discussion
            assert "resolved" in discussion
            assert "comments" in discussion

            # Comments should have proper structure
            for comment in discussion["comments"]:
                assert "text" in comment
                assert "author" in comment
                assert "username" in comment["author"]
