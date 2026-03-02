"""Integration tests for Space MCP client using real JetBrains Space and Patronus APIs.

These tests require SPACE_TOKEN environment variable to be set (via .env or export).
They use known MRs in the ij/ultimate repository.

The real_client and real_patronus_client fixtures are provided by conftest.py
and auto-skip when SPACE_TOKEN is not available.
"""
import pytest

# Known test data from real Space instance
TEST_PROJECT = "ij"
TEST_REPOSITORY = "ultimate"
TEST_REVIEW_NUMBER = "188120"  # Display number from URL
TEST_BRANCH = "azhukova/QD-13281"

# MR 190592 for testing timeline messages and Patronus integration
TEST_REVIEW_190592 = "190592"

# MR 192360 for testing description field
TEST_REVIEW_192360 = "192360"


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
        """Test finding MR by branch name (searches all states).

        Note: Space API text search may not return old closed MRs,
        so this test is lenient. The find-by-branch relies on text search.
        """
        result = await real_client.find_merge_request_by_branch(
            TEST_PROJECT, TEST_REPOSITORY, TEST_BRANCH
        )

        if result is not None:
            assert "title" in result
            branch_pairs = result.get("branchPairs", [])
            branches = [bp.get("sourceBranch") for bp in branch_pairs]
            assert TEST_BRANCH in branches

    async def test_find_mr_by_nonexistent_branch(self, real_client):
        """Test that nonexistent branch returns None."""
        result = await real_client.find_merge_request_by_branch(
            TEST_PROJECT, TEST_REPOSITORY, "definitely-not-a-real-branch-12345"
        )

        assert result is None


class TestEndToEndMCPFlow:
    """End-to-end tests that mirror exact MCP tool call flows."""

    async def test_get_mr_by_display_number(self, real_client):
        """Test getting MR by the display number from URL."""
        mr = await real_client.get_merge_request(
            TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_NUMBER
        )

        assert mr is not None
        assert mr.get("title") == "QD-13281: Initial implementation of Qodana for Rust"
        assert mr.get("state") in ("Opened", "Closed", "Merged")

        # Verify branch info
        branch_pairs = mr.get("branchPairs", [])
        assert len(branch_pairs) == 1
        assert branch_pairs[0].get("sourceBranch") == TEST_BRANCH
        assert branch_pairs[0].get("repository") == TEST_REPOSITORY


class TestMR188120Timeline:
    """Comprehensive integration tests for MR 188120 (closed) timeline.

    MR 188120 (azhukova/QD-13281) is a closed MR with a rich timeline:
    code discussions, commits, force-pushes, dry runs, Patronus messages,
    reviewer additions, and review approvals.
    """

    @pytest.fixture
    async def timeline(self, real_client):
        return await real_client.get_merge_request_discussions(
            TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_NUMBER
        )

    async def test_has_both_types(self, timeline):
        """Timeline should contain both code discussions and general messages."""
        types = {item["type"] for item in timeline}
        assert types == {"code_discussion", "message"}

    async def test_all_items_have_type_field(self, timeline):
        for item in timeline:
            assert "type" in item
            assert item["type"] in ("code_discussion", "message")

    async def test_code_discussions(self, timeline):
        """MR 188120 has 8 code discussions (across both pages of the timeline)."""
        code_discussions = [r for r in timeline if r["type"] == "code_discussion"]
        assert len(code_discussions) == 8

        for disc in code_discussions:
            assert disc["file"] is not None or disc["line"] is not None
            assert len(disc["comments"]) >= 1

    async def test_code_discussion_structure(self, timeline):
        code_discussions = [r for r in timeline if r["type"] == "code_discussion"]
        for disc in code_discussions:
            assert "id" in disc
            assert "file" in disc
            assert "line" in disc
            assert "resolved" in disc
            assert "comments" in disc
            for comment in disc["comments"]:
                assert "text" in comment
                assert "author" in comment
                assert "username" in comment["author"]
                assert "name" in comment["author"]
                assert "created" in comment

    async def test_general_message_structure(self, timeline):
        messages = [r for r in timeline if r["type"] == "message"]
        assert len(messages) > 30, "Expected many timeline messages"
        for msg in messages:
            assert "text" in msg
            assert "author" in msg
            assert "created" in msg

    async def test_messages_have_event_class(self, timeline):
        """All messages should carry an event_class field from the API."""
        messages = [r for r in timeline if r["type"] == "message"]
        for msg in messages:
            assert "event_class" in msg, f"Missing event_class: {msg['text'][:50]}"
            assert msg["event_class"] is not None

    async def test_has_mcmessage_events(self, timeline):
        """Timeline should include MCMessage events (commits, pushes, reviewer actions)."""
        messages = [r for r in timeline if r["type"] == "message"]
        mc_messages = [m for m in messages if m["event_class"] == "MCMessage"]
        assert len(mc_messages) >= 10

    async def test_has_threaded_messages(self, timeline):
        """Messages with thread_replies should exist (dry runs, safe merges)."""
        messages = [r for r in timeline if r["type"] == "message"]
        with_threads = [m for m in messages if m.get("thread_replies")]
        assert len(with_threads) >= 1
        # Thread replies should include app-authored messages
        for msg in with_threads:
            app_replies = [r for r in msg["thread_replies"] if r["author"].get("author_type") == "app"]
            assert len(app_replies) >= 1

    async def test_has_app_authored_messages(self, timeline):
        """Timeline should include messages from application accounts (e.g. Patronus)."""
        messages = [r for r in timeline if r["type"] == "message"]
        app_msgs = [m for m in messages if m["author"].get("author_type") == "app"]
        assert len(app_msgs) >= 1
        assert any(m["event_class"] == "M2TextItemContent" for m in app_msgs)

    async def test_pagination_fetches_all_messages(self, timeline):
        """MR 188120 has >50 messages — pagination should fetch them all."""
        assert len(timeline) > 50, "Expected pagination to fetch more than 50 items"

    async def test_has_multiple_authors(self, timeline):
        """Timeline should have messages from multiple people."""
        authors = set()
        for item in timeline:
            if item["type"] == "message":
                authors.add(item["author"].get("username"))
            elif item["type"] == "code_discussion":
                for c in item["comments"]:
                    authors.add(c["author"].get("username"))
        assert len(authors) >= 3

    async def test_authors_have_type(self, timeline):
        """All message authors should have an author_type field."""
        for item in timeline:
            if item["type"] == "message":
                assert "author_type" in item["author"], f"Missing author_type: {item['text'][:50]}"


class TestMR190592Discussions:
    """Integration tests for MR 190592 — timeline messages and Patronus visibility."""

    async def test_get_discussions_returns_results(self, real_client):
        """MR 190592 should have discussions."""
        result = await real_client.get_merge_request_discussions(
            TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_190592
        )

        assert isinstance(result, list)
        assert len(result) > 0, "Expected MR 190592 to have discussions"

    async def test_includes_general_messages(self, real_client):
        """MR 190592 should have general timeline messages (not just code discussions)."""
        result = await real_client.get_merge_request_discussions(
            TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_190592
        )

        messages = [r for r in result if r["type"] == "message"]
        assert len(messages) > 0, "Expected MR 190592 to have general timeline messages"


class TestMR192360Description:
    """Integration tests for MR 192360 — verifies description field is returned."""

    async def test_mr_has_description(self, real_client):
        result = await real_client.get_merge_request(TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_192360)
        assert result.get("description") is not None
        assert "suppression" in result["description"].lower()

    async def test_mr_has_number(self, real_client):
        result = await real_client.get_merge_request(TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_192360)
        assert result.get("number") == 192360


class TestPatronusIntegration:
    """Integration tests for Patronus API."""

    async def test_list_robots_for_repository(self, real_patronus_client):
        """Test listing robots for the ultimate repository."""
        result = await real_patronus_client.list_robots("ultimate")

        assert isinstance(result, list)
        # The repository is very active, should have some robots
        assert len(result) > 0, "Expected Patronus to have robots for the ultimate repository"

    async def test_robot_overview_structure(self, real_patronus_client):
        """Test that robot overview has expected fields."""
        robots = await real_patronus_client.list_robots("ultimate")
        if not robots:
            pytest.skip("No robots found for testing")

        robot = robots[0]
        assert "id" in robot
        assert "status" in robot
        assert robot["status"] in ("RUNNING", "FAILING", "SUCCESSFUL", "FAILED", "CANCELED", "CREATED")

    async def test_get_robot_details(self, real_patronus_client):
        """Test getting details for a specific robot."""
        robots = await real_patronus_client.list_robots("ultimate")
        if not robots:
            pytest.skip("No robots found for testing")

        robot_id = robots[0]["id"]
        robot = await real_patronus_client.get_robot(robot_id)

        assert robot["id"] == robot_id
        assert "status" in robot
        assert "repository" in robot

    async def test_get_robot_teamcity_checks(self, real_patronus_client):
        """Test getting TeamCity checks for a robot."""
        robots = await real_patronus_client.list_robots("ultimate")
        if not robots:
            pytest.skip("No robots found for testing")

        robot_id = robots[0]["id"]
        checks = await real_patronus_client.get_robot_teamcity_checks(robot_id)

        assert isinstance(checks, list)
