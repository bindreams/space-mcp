"""Integration tests for Space MCP client using real JetBrains Space and Patronus APIs.

These tests require SPACE_TOKEN environment variable to be set (via .env or export).
They use known MRs in the ij/ultimate repository.

The real_client and real_patronus_client fixtures are provided by conftest.py
and auto-skip when SPACE_TOKEN is not available.
"""
from __future__ import annotations

import pytest

from space.models import (
    CodeDiscussion,
    MergeRequest,
    MRState,
    PatronusCheckRun,
    PatronusRun,
    RunStatus,
    SpaceAccount,
    SpaceApp,
    TimelineEventClass,
    TimelineMessage,
)

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


class TestMR192360Description:

    async def test_mr_has_description(self, real_client):
        result = await real_client.get_merge_request(TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_192360)
        assert result.description is not None
        assert "suppression" in result.description.lower()

    async def test_mr_has_number(self, real_client):
        result = await real_client.get_merge_request(TEST_PROJECT, TEST_REPOSITORY, TEST_REVIEW_192360)
        assert result.number == 192360


# Robot 494efb3a has a known failure
TEST_FAILED_ROBOT = "494efb3a-55cd-460a-9ed9-e0aa64a4b6c5"


class TestPatronusFailedRobot:

    async def test_problems_have_title(self, real_patronus_client):
        problems = await real_patronus_client.get_robot_problems(TEST_FAILED_ROBOT)
        assert len(problems) > 0
        for p in problems:
            assert p.title
            assert p.title != "?"

    async def test_smoke_tests_check_failed(self, real_patronus_client):
        checks = await real_patronus_client.get_robot_teamcity_checks(TEST_FAILED_ROBOT)
        smoke = [c for c in checks if c.config.build_configuration_id == "ijplatform_master_Idea_SmokeTests_Aggregator"]
        assert len(smoke) == 1
        assert smoke[0].status == RunStatus.FAILURE

    @pytest.fixture
    async def smoke_attempt_details(self, real_patronus_client):
        checks = await real_patronus_client.get_robot_teamcity_checks(TEST_FAILED_ROBOT)
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


class TestPatronusIntegration:

    async def test_list_robots_for_repository(self, real_patronus_client):
        result = await real_patronus_client.list_robots("ultimate")
        assert isinstance(result, list)
        assert len(result) > 0

    async def test_robot_overview_structure(self, real_patronus_client):
        robots = await real_patronus_client.list_robots("ultimate")
        if not robots:
            pytest.skip("No robots found")
        robot = robots[0]
        assert isinstance(robot, PatronusRun)
        assert robot.status is not None

    async def test_get_robot_details(self, real_patronus_client):
        robots = await real_patronus_client.list_robots("ultimate")
        if not robots:
            pytest.skip("No robots found")
        robot = await real_patronus_client.get_robot(robots[0].id)
        assert isinstance(robot, PatronusRun)
        assert robot.id == robots[0].id

    async def test_get_robot_teamcity_checks(self, real_patronus_client):
        robots = await real_patronus_client.list_robots("ultimate")
        if not robots:
            pytest.skip("No robots found")
        checks = await real_patronus_client.get_robot_teamcity_checks(robots[0].id)
        assert isinstance(checks, list)

    async def test_cancel_finished_robot_is_idempotent(self, real_patronus_client):
        await real_patronus_client.cancel_robot(TEST_FAILED_ROBOT)

    async def test_get_me(self, real_patronus_client):
        me = await real_patronus_client.get_me("ultimate")
        assert me["type"] == "USER"
        assert "id" in me
        assert "name" in me
