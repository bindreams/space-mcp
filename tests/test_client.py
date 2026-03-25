from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import pytest
import httpx

from space.client import SpaceClient, _error_detail, _matches_repository, validate_token
from space.models import (
    BranchPair,
    CodeDiscussion,
    FileAttachment,
    ImageAttachment,
    MergeRequest,
    MRState,
    SpaceAccount,
    SpaceApp,
    TimelineEventClass,
    TimelineMessage,
)


class TestMatchesRepository:

    def test_matches_dict_repository(self):
        bp = {"repository": {"name": "ultimate"}}
        assert _matches_repository(bp, "ultimate") is True

    def test_rejects_dict_repository(self):
        bp = {"repository": {"name": "community"}}
        assert _matches_repository(bp, "ultimate") is False

    def test_matches_string_repository(self):
        bp = {"repository": "ultimate"}
        assert _matches_repository(bp, "ultimate") is True

    def test_rejects_string_repository(self):
        bp = {"repository": "community"}
        assert _matches_repository(bp, "ultimate") is False

    def test_none_repository(self):
        bp = {"repository": None}
        assert _matches_repository(bp, "ultimate") is False

    def test_missing_repository_key(self):
        bp = {}
        assert _matches_repository(bp, "ultimate") is False


class TestErrorDetail:
    """Tests for _error_detail fallback chain."""

    def test_returns_text_when_present(self):
        response = httpx.Response(400, request=httpx.Request("GET", "https://x"), text="Bad request body")
        assert _error_detail(response) == "Bad request body"

    def test_returns_reason_when_text_empty(self):
        response = httpx.Response(500, request=httpx.Request("GET", "https://x"), text="")
        detail = _error_detail(response)
        assert detail == response.reason_phrase or detail == "HTTP 500"

    def test_returns_http_code_when_both_empty(self):
        response = httpx.Response(599, request=httpx.Request("GET", "https://x"), text="")
        assert _error_detail(response) == "HTTP 599"


class TestSpaceClientInit:

    def test_init(self):
        client = SpaceClient(token="test-token")
        assert client.base_url == "https://jetbrains.team"
        assert client.token == "test-token"


class TestSpaceClientHeaders:

    def test_headers_contains_bearer_token(self, space_client):
        headers = space_client._headers()
        assert headers["Authorization"] == "Bearer test-token"

    def test_headers_contains_accept_json(self, space_client):
        headers = space_client._headers()
        assert headers["Accept"] == "application/json"


class TestGetMergeRequest:

    async def test_get_merge_request_returns_model(self, httpx_mock, space_client, sample_merge_request, test_accounts):
        httpx_mock.add_response(json=sample_merge_request)

        result = await space_client.get_merge_request("ij", "ultimate", "123456")

        assert isinstance(result, MergeRequest)
        assert result.id == "123456"
        assert result.title == "Fix authentication bug"
        assert result.state == MRState.OPENED
        assert result.number == 188120

    async def test_get_merge_request_resolves_author(self, httpx_mock, space_client, sample_merge_request, test_accounts):
        httpx_mock.add_response(json=sample_merge_request)

        result = await space_client.get_merge_request("ij", "ultimate", "123456")

        assert isinstance(result.created_by, SpaceAccount)
        assert result.created_by.username == "azhukova"

    async def test_get_merge_request_resolves_participants(self, httpx_mock, space_client, sample_merge_request, test_accounts):
        httpx_mock.add_response(json=sample_merge_request)

        result = await space_client.get_merge_request("ij", "ultimate", "123456")

        assert len(result.participants) == 1
        assert result.participants[0].user.username == "jdoe"
        assert result.participants[0].role.value == "Reviewer"

    async def test_get_merge_request_branch_pairs(self, httpx_mock, space_client, sample_merge_request, test_accounts):
        httpx_mock.add_response(json=sample_merge_request)

        result = await space_client.get_merge_request("ij", "ultimate", "123456")

        assert len(result.branch_pairs) == 1
        assert result.branch_pairs[0].source_branch == "azhukova/fix-auth"
        assert result.branch_pairs[0].repository == "ultimate"

    async def test_get_merge_request_url_format(self, httpx_mock, space_client, sample_merge_request, test_accounts):
        httpx_mock.add_response(json=sample_merge_request)

        await space_client.get_merge_request("ij", "ultimate", "123456")

        request = httpx_mock.get_request()
        assert "projects/key:ij/code-reviews/number:123456" in str(request.url)

    async def test_get_merge_request_not_found(self, httpx_mock, space_client):
        httpx_mock.add_response(status_code=404)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await space_client.get_merge_request("ij", "ultimate", "nonexistent")

        assert exc_info.value.response.status_code == 404

    async def test_get_merge_request_unauthorized(self, httpx_mock, space_client):
        httpx_mock.add_response(status_code=401)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await space_client.get_merge_request("ij", "ultimate", "123456")

        assert exc_info.value.response.status_code == 401

    async def test_get_merge_request_network_error(self, httpx_mock, space_client):
        httpx_mock.add_exception(httpx.ConnectError("Connection failed"))

        with pytest.raises(httpx.ConnectError):
            await space_client.get_merge_request("ij", "ultimate", "123456")


class TestGetMergeRequestDiscussions:

    async def test_get_discussions_code_discussion(self, httpx_mock, space_client, sample_review_with_channel, sample_feed_messages, sample_discussion_thread, test_accounts):
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages)
        httpx_mock.add_response(json=sample_discussion_thread)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        code_discussions = [r for r in result if isinstance(r, CodeDiscussion)]
        assert len(code_discussions) == 1
        assert code_discussions[0].file == "/src/auth.py"
        assert code_discussions[0].line == 42
        assert len(code_discussions[0].comments) == 2
        assert code_discussions[0].comments[0].text == "Please add tests for this change"

    async def test_get_discussions_empty_feed(self, httpx_mock, space_client, sample_review_with_channel):
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json={"messages": []})

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        assert result == []

    async def test_get_discussions_no_channel(self, httpx_mock, space_client):
        httpx_mock.add_response(json={})

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        assert result == []

    async def test_get_discussions_includes_general_messages(
        self, httpx_mock, space_client, sample_review_with_channel, sample_feed_messages_with_general, sample_discussion_thread, test_accounts,
    ):
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages_with_general)
        httpx_mock.add_response(json=sample_discussion_thread)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        code_discussions = [r for r in result if isinstance(r, CodeDiscussion)]
        messages = [r for r in result if isinstance(r, TimelineMessage)]

        assert len(code_discussions) == 1
        assert len(messages) == 2

    async def test_get_discussions_app_messages_visible(
        self, httpx_mock, space_client, sample_review_with_channel, sample_feed_messages_with_general, sample_discussion_thread, test_accounts,
    ):
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages_with_general)
        httpx_mock.add_response(json=sample_discussion_thread)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        messages = [r for r in result if isinstance(r, TimelineMessage)]
        app_msgs = [m for m in messages if isinstance(m.author, SpaceApp)]
        assert len(app_msgs) == 1
        assert app_msgs[0].event_class == TimelineEventClass.M2_TEXT_ITEM

    async def test_get_discussions_messages_have_event_class(
        self, httpx_mock, space_client, sample_review_with_channel, sample_feed_messages_with_general, sample_discussion_thread, test_accounts,
    ):
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages_with_general)
        httpx_mock.add_response(json=sample_discussion_thread)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        messages = [r for r in result if isinstance(r, TimelineMessage)]
        for msg in messages:
            assert msg.event_class is not None


class TestListMergeRequests:

    async def test_list_merge_requests_success(self, httpx_mock, space_client, sample_merge_request_list, test_accounts):
        httpx_mock.add_response(json=sample_merge_request_list)

        result = await space_client.list_merge_requests("ij", "ultimate")

        assert len(result) == 2
        assert isinstance(result[0], MergeRequest)
        assert result[0].id == "123456"

    async def test_list_merge_requests_with_state_filter(self, httpx_mock, space_client, sample_merge_request_list, test_accounts):
        httpx_mock.add_response(json=sample_merge_request_list)

        await space_client.list_merge_requests("ij", "ultimate", state="Open")

        request = httpx_mock.get_request()
        assert "state=Opened" in str(request.url)

    async def test_list_merge_requests_filters_by_repository_client_side(self, httpx_mock, space_client, test_accounts):
        mixed_repos_response = {
            "data": [
                {"review": {"id": "123456", "title": "MR in ultimate", "state": "Opened", "createdAt": 1736937000000,
                            "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                            "branchPairs": [{"sourceBranch": "feature/test", "targetBranch": "master", "repository": {"name": "ultimate"}}]}},
                {"review": {"id": "789012", "title": "MR in community", "state": "Opened", "createdAt": 1736937000000,
                            "createdBy": {"id": "user-jdoe", "name": "John Doe", "username": "jdoe"},
                            "branchPairs": [{"sourceBranch": "feature/other", "targetBranch": "master", "repository": {"name": "community"}}]}},
            ]
        }
        httpx_mock.add_response(json=mixed_repos_response)

        result = await space_client.list_merge_requests("ij", "ultimate")

        assert len(result) == 1
        assert result[0].id == "123456"

    async def test_list_merge_requests_with_branch_filter(self, httpx_mock, space_client, sample_merge_request_list, test_accounts):
        httpx_mock.add_response(json=sample_merge_request_list)

        result = await space_client.list_merge_requests("ij", "ultimate", branch="azhukova/fix-auth")

        assert len(result) == 1
        assert result[0].id == "123456"

    async def test_list_merge_requests_empty(self, httpx_mock, space_client, empty_merge_request_list):
        httpx_mock.add_response(json=empty_merge_request_list)

        result = await space_client.list_merge_requests("ij", "ultimate")

        assert result == []

    async def test_paginates_when_filtering_by_branch(self, httpx_mock, space_client, test_accounts, monkeypatch):
        """First page has no branch matches, second page has a match."""
        import space.pagination
        monkeypatch.setattr(space.pagination, "_PAGE_SIZE", 2)

        page1 = {"data": [
            {"review": {"id": "100", "title": "Unrelated 1", "state": "Opened", "createdAt": 1736937000000,
                         "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                         "branchPairs": [{"sourceBranch": "other/branch", "targetBranch": "main", "repository": {"name": "ultimate"}}]}},
            {"review": {"id": "101", "title": "Unrelated 2", "state": "Opened", "createdAt": 1736937000000,
                         "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                         "branchPairs": [{"sourceBranch": "other/branch2", "targetBranch": "main", "repository": {"name": "ultimate"}}]}},
        ]}
        # Page 2 overlaps by 1 (item 101), then has the target
        page2 = {"data": [
            {"review": {"id": "101", "title": "Unrelated 2", "state": "Opened", "createdAt": 1736937000000,
                         "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                         "branchPairs": [{"sourceBranch": "other/branch2", "targetBranch": "main", "repository": {"name": "ultimate"}}]}},
            {"review": {"id": "200", "title": "Target MR", "state": "Opened", "createdAt": 1736937000000,
                         "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                         "branchPairs": [{"sourceBranch": "azhukova/fix-auth", "targetBranch": "main", "repository": {"name": "ultimate"}}]}},
        ]}
        # Page 3 is partial (signals end)
        page3 = {"data": [
            {"review": {"id": "200", "title": "Target MR", "state": "Opened", "createdAt": 1736937000000,
                         "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                         "branchPairs": [{"sourceBranch": "azhukova/fix-auth", "targetBranch": "main", "repository": {"name": "ultimate"}}]}},
        ]}
        httpx_mock.add_response(json=page1)
        httpx_mock.add_response(json=page2)
        httpx_mock.add_response(json=page3)

        result = await space_client.list_merge_requests("ij", "ultimate", branch="azhukova/fix-auth")

        assert len(result) == 1
        assert result[0].id == "200"

    async def test_paginates_when_filtering_by_repository(self, httpx_mock, space_client, test_accounts, monkeypatch):
        """First page has wrong repo, second page has right repo."""
        import space.pagination
        monkeypatch.setattr(space.pagination, "_PAGE_SIZE", 2)

        page1 = {"data": [
            {"review": {"id": "100", "title": "Wrong repo 1", "state": "Opened", "createdAt": 1736937000000,
                         "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                         "branchPairs": [{"sourceBranch": "feature/x", "targetBranch": "main", "repository": {"name": "community"}}]}},
            {"review": {"id": "101", "title": "Wrong repo 2", "state": "Opened", "createdAt": 1736937000000,
                         "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                         "branchPairs": [{"sourceBranch": "feature/z", "targetBranch": "main", "repository": {"name": "community"}}]}},
        ]}
        page2 = {"data": [
            {"review": {"id": "101", "title": "Wrong repo 2", "state": "Opened", "createdAt": 1736937000000,
                         "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                         "branchPairs": [{"sourceBranch": "feature/z", "targetBranch": "main", "repository": {"name": "community"}}]}},
            {"review": {"id": "200", "title": "Right repo", "state": "Opened", "createdAt": 1736937000000,
                         "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                         "branchPairs": [{"sourceBranch": "feature/y", "targetBranch": "main", "repository": {"name": "ultimate"}}]}},
        ]}
        page3 = {"data": [
            {"review": {"id": "200", "title": "Right repo", "state": "Opened", "createdAt": 1736937000000,
                         "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                         "branchPairs": [{"sourceBranch": "feature/y", "targetBranch": "main", "repository": {"name": "ultimate"}}]}},
        ]}
        httpx_mock.add_response(json=page1)
        httpx_mock.add_response(json=page2)
        httpx_mock.add_response(json=page3)

        result = await space_client.list_merge_requests("ij", "ultimate")

        assert len(result) == 1
        assert result[0].id == "200"

    async def test_no_text_derived_from_branch(self, httpx_mock, space_client, sample_merge_request_list, test_accounts):
        """branch parameter must NOT cause text param in API request."""
        httpx_mock.add_response(json=sample_merge_request_list)

        await space_client.list_merge_requests("ij", "ultimate", branch="azhukova/fix-auth")

        request = httpx_mock.get_request()
        params = parse_qs(urlparse(str(request.url)).query)
        assert "text" not in params

    async def test_explicit_text_passed_through(self, httpx_mock, space_client, sample_merge_request_list, test_accounts):
        """Explicit text parameter is passed to API."""
        httpx_mock.add_response(json=sample_merge_request_list)

        await space_client.list_merge_requests("ij", "ultimate", text="search term")

        request = httpx_mock.get_request()
        params = parse_qs(urlparse(str(request.url)).query)
        assert params["text"] == ["search term"]


class TestFindMergeRequestByBranch:

    async def test_find_mr_by_branch_found(self, httpx_mock, space_client, sample_merge_request_list, sample_merge_request, test_accounts):
        httpx_mock.add_response(json=sample_merge_request_list)
        httpx_mock.add_response(json=sample_merge_request)

        result = await space_client.find_merge_request_by_branch("ij", "ultimate", "azhukova/fix-auth")

        assert result is not None
        assert result.id == "123456"

    async def test_find_mr_by_branch_not_found(self, httpx_mock, space_client, empty_merge_request_list):
        # Two empty responses: text-search call + full-scan fallback
        httpx_mock.add_response(json=empty_merge_request_list)
        httpx_mock.add_response(json=empty_merge_request_list)

        result = await space_client.find_merge_request_by_branch("ij", "ultimate", "nonexistent/branch")

        assert result is None

    async def test_find_mr_fast_path_with_text(self, space_client, test_accounts):
        """Text search finds the MR on first call — only 1 list call made."""
        mr = MergeRequest(
            id="123456", number=188120, title="Fix auth",
            state=MRState.OPENED, created_at=None, description=None,
            created_by=SpaceAccount(id="user-azhukova", username="azhukova",
                                    email="a@test.com", first_name="Anna", last_name="Zhukova"),
            participants=(), branch_pairs=(BranchPair(source_branch="azhukova/fix-auth",
                                                       target_branch="main", repository="ultimate"),),
        )
        call_args_list = []

        async def mock_list(*args, **kwargs):
            call_args_list.append(kwargs)
            if kwargs.get("text"):
                return [mr]
            return []

        async def mock_get(*args, **kwargs):
            return mr

        with patch.object(space_client, "list_merge_requests", side_effect=mock_list), \
             patch.object(space_client, "get_merge_request", side_effect=mock_get):
            result = await space_client.find_merge_request_by_branch("ij", "ultimate", "azhukova/fix-auth")

        assert result is not None
        assert len(call_args_list) == 1  # only the text-search call
        assert call_args_list[0]["limit"] == 1

    async def test_find_mr_falls_back_to_full_scan(self, space_client, test_accounts):
        """Text search returns empty, full scan finds the MR — 2 list calls."""
        mr = MergeRequest(
            id="123456", number=188120, title="Fix auth",
            state=MRState.OPENED, created_at=None, description=None,
            created_by=SpaceAccount(id="user-azhukova", username="azhukova",
                                    email="a@test.com", first_name="Anna", last_name="Zhukova"),
            participants=(), branch_pairs=(BranchPair(source_branch="azhukova/fix-auth",
                                                       target_branch="main", repository="ultimate"),),
        )
        call_args_list = []

        async def mock_list(*args, **kwargs):
            call_args_list.append(kwargs)
            if kwargs.get("text"):
                return []  # text search finds nothing
            return [mr]  # full scan finds it

        async def mock_get(*args, **kwargs):
            return mr

        with patch.object(space_client, "list_merge_requests", side_effect=mock_list), \
             patch.object(space_client, "get_merge_request", side_effect=mock_get):
            result = await space_client.find_merge_request_by_branch("ij", "ultimate", "azhukova/fix-auth")

        assert result is not None
        assert len(call_args_list) == 2  # text call + full scan
        assert call_args_list[0]["limit"] == 1
        assert call_args_list[1]["limit"] == 1


class TestSetMergeRequestState:

    async def test_close_mr_success(self, httpx_mock, space_client):
        httpx_mock.add_response(status_code=200, text="")

        await space_client.set_merge_request_state("ij", "190592", "Closed")

        request = httpx_mock.get_request()
        assert request.method == "PATCH"
        import json
        body = json.loads(request.content)
        assert body == {"state": "Closed"}

    async def test_set_state_url_format_numeric(self, httpx_mock, space_client):
        httpx_mock.add_response(status_code=200, text="")

        await space_client.set_merge_request_state("ij", "190592", "Closed")

        request = httpx_mock.get_request()
        assert "code-reviews/number:190592/state" in str(request.url)

    async def test_set_state_not_found(self, httpx_mock, space_client):
        httpx_mock.add_response(status_code=404, text="Not found")

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await space_client.set_merge_request_state("ij", "999999", "Closed")

        assert exc_info.value.response.status_code == 404


class TestCreateMergeRequest:

    async def test_create_mr_returns_model(self, httpx_mock, space_client, sample_created_merge_request):
        httpx_mock.add_response(json=sample_created_merge_request, status_code=200)

        result = await space_client.create_merge_request(
            "ij", "ultimate", "azhukova/new-feature", "master", "New feature",
        )

        assert isinstance(result, MergeRequest)
        assert result.number == 194200
        assert result.title == "New feature"

    async def test_create_mr_request_body(self, httpx_mock, space_client, sample_created_merge_request):
        httpx_mock.add_response(json=sample_created_merge_request, status_code=200)

        await space_client.create_merge_request(
            "ij", "ultimate", "azhukova/new-feature", "master", "New feature",
            description="Fix the auth bug",
        )

        request = httpx_mock.get_request()
        import json
        body = json.loads(request.content)
        assert body["repository"] == "ultimate"
        assert body["sourceBranch"] == "azhukova/new-feature"
        assert body["title"] == "New feature"
        assert body["description"] == "Fix the auth bug"

    async def test_create_mr_error(self, httpx_mock, space_client):
        httpx_mock.add_response(
            status_code=400,
            json={"error": "BAD_REQUEST", "description": "Branch not found"},
        )

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await space_client.create_merge_request(
                "ij", "ultimate", "nonexistent", "master", "Test",
            )

        assert exc_info.value.response.status_code == 400


class TestStartSafeMerge:

    async def test_start_safe_merge_with_internal_id(self, httpx_mock, space_client):
        httpx_mock.add_response(json={"jobId": "job-1"}, status_code=200)

        await space_client.start_safe_merge("ij", "2eTFJg4dJrmL")

        request = httpx_mock.get_request()
        assert request.method == "POST"
        import json
        body = json.loads(request.content)
        assert body["mergeRequestId"] == "id:2eTFJg4dJrmL"

    async def test_start_safe_merge_resolves_numeric_id(self, httpx_mock, space_client, test_accounts):
        # First call: get_merge_request to resolve numeric ID
        httpx_mock.add_response(json={"id": "2eTFJg4dJrmL", "number": 190592, "title": "T", "state": "Opened", "createdAt": 1736937000000})
        # Second call: the actual safe-merge POST
        httpx_mock.add_response(json={"jobId": "job-1"}, status_code=200)

        await space_client.start_safe_merge("ij", "190592")

        requests = httpx_mock.get_requests()
        assert len(requests) == 2
        assert "code-reviews/number:190592" in str(requests[0].url)
        import json
        body = json.loads(requests[1].content)
        assert body["mergeRequestId"] == "id:2eTFJg4dJrmL"

    async def test_start_safe_merge_default_operation(self, httpx_mock, space_client):
        httpx_mock.add_response(json={}, status_code=200)

        await space_client.start_safe_merge("ij", "abc123")

        request = httpx_mock.get_request()
        import json
        body = json.loads(request.content)
        assert body["mergeOptions"]["operation"] == "DryRun"

    async def test_start_safe_merge_returns_response(self, httpx_mock, space_client):
        httpx_mock.add_response(json={"jobId": "job-123"}, status_code=200)

        result = await space_client.start_safe_merge("ij", "abc123")

        assert result == {"jobId": "job-123"}


class TestDiscussionsWithAttachments:

    async def test_includes_attachments(
        self, httpx_mock, space_client,
        sample_review_with_channel, sample_feed_messages_with_attachments, test_accounts,
    ):
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages_with_attachments)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        messages = [r for r in result if isinstance(r, TimelineMessage)]
        msg_with_atts = messages[0]
        assert len(msg_with_atts.attachments) == 2
        assert isinstance(msg_with_atts.attachments[0], ImageAttachment)
        assert isinstance(msg_with_atts.attachments[1], FileAttachment)
        assert msg_with_atts.attachments[1].name == "report.txt"

    async def test_skips_non_file_attachments(
        self, httpx_mock, space_client,
        sample_review_with_channel, sample_feed_messages_with_attachments, test_accounts,
    ):
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages_with_attachments)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        messages = [r for r in result if isinstance(r, TimelineMessage)]
        # Second message has only an UnfurlAttachment — empty tuple
        msg_unfurl_only = messages[1]
        assert msg_unfurl_only.attachments == ()

    async def test_thread_replies_include_attachments(
        self, httpx_mock, space_client,
        sample_review_with_channel,
        sample_feed_messages,
        sample_discussion_thread_with_attachments, test_accounts,
    ):
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages)
        httpx_mock.add_response(json=sample_discussion_thread_with_attachments)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        code_discussions = [r for r in result if isinstance(r, CodeDiscussion)]
        assert len(code_discussions) == 1
        comments = code_discussions[0].comments
        # First comment has attachment, second does not
        assert len(comments[0].attachments) == 1
        assert comments[0].attachments[0].name == "build.log"
        assert comments[1].attachments == ()


class TestDownloadAttachment:

    async def test_download_success(self, httpx_mock, space_client):
        httpx_mock.add_response(
            content=b"file content here",
            headers={"content-type": "text/plain"},
        )
        content, content_type = await space_client.download_attachment("file-001")
        assert content == b"file content here"
        assert content_type == "text/plain"

    async def test_download_url_format(self, httpx_mock, space_client):
        httpx_mock.add_response(content=b"data")
        await space_client.download_attachment("file-001")
        request = httpx_mock.get_request()
        assert str(request.url) == "https://jetbrains.team/d/file-001"

    async def test_download_not_found(self, httpx_mock, space_client):
        httpx_mock.add_response(status_code=404)
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await space_client.download_attachment("nonexistent")
        assert exc_info.value.response.status_code == 404


class TestValidateToken:
    async def test_valid_token_returns_profile(self, httpx_mock):
        httpx_mock.add_response(json={
            "username": "azhukova",
            "emails": [{"email": "anna@jetbrains.com"}],
        })
        result = await validate_token("good-token")
        assert result["username"] == "azhukova"
        assert result["emails"][0]["email"] == "anna@jetbrains.com"

    async def test_requests_correct_url_and_fields(self, httpx_mock):
        httpx_mock.add_response(json={"username": "x", "emails": []})
        await validate_token("tok")
        request = httpx_mock.get_request()
        assert "team-directory/profiles/me" in str(request.url)
        assert "username" in str(request.url)
        assert "emails" in str(request.url)

    async def test_invalid_token_401(self, httpx_mock):
        httpx_mock.add_response(status_code=401)
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await validate_token("bad-token")
        assert exc_info.value.response.status_code == 401

    async def test_invalid_token_403(self, httpx_mock):
        httpx_mock.add_response(status_code=403)
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await validate_token("bad-token")
        assert exc_info.value.response.status_code == 403

    async def test_server_error(self, httpx_mock):
        httpx_mock.add_response(status_code=500)
        with pytest.raises(httpx.HTTPStatusError):
            await validate_token("tok")
