import pytest
import httpx

from space.client import SpaceClient


class TestSpaceClientInit:
    """Tests for SpaceClient constructor."""

    def test_init_with_defaults(self):
        client = SpaceClient(token="test-token")
        assert client.base_url == "https://jetbrains.team"
        assert client.token == "test-token"

    def test_init_with_custom_base_url(self):
        client = SpaceClient(token="test-token", base_url="https://custom.space.example.com")
        assert client.base_url == "https://custom.space.example.com"

    def test_init_strips_trailing_slash(self):
        client = SpaceClient(token="test-token", base_url="https://example.com/")
        assert client.base_url == "https://example.com"


class TestSpaceClientHeaders:
    """Tests for _headers method."""

    def test_headers_contains_bearer_token(self, space_client):
        headers = space_client._headers()
        assert headers["Authorization"] == "Bearer test-token"

    def test_headers_contains_accept_json(self, space_client):
        headers = space_client._headers()
        assert headers["Accept"] == "application/json"


class TestGetMergeRequest:
    """Tests for get_merge_request method."""

    async def test_get_merge_request_success(self, httpx_mock, space_client, sample_merge_request):
        httpx_mock.add_response(json=sample_merge_request)

        result = await space_client.get_merge_request("ij", "ultimate", "123456")

        assert result == sample_merge_request
        assert result["id"] == "123456"
        assert result["title"] == "Fix authentication bug"

    async def test_get_merge_request_url_format(self, httpx_mock, space_client, sample_merge_request):
        httpx_mock.add_response(json=sample_merge_request)

        await space_client.get_merge_request("ij", "ultimate", "123456")

        request = httpx_mock.get_request()
        # Numeric IDs use 'number:' prefix, alphanumeric use 'id:'
        assert "projects/key:ij/code-reviews/number:123456" in str(request.url)

    async def test_get_merge_request_params(self, httpx_mock, space_client, sample_merge_request):
        httpx_mock.add_response(json=sample_merge_request)

        await space_client.get_merge_request("ij", "ultimate", "123456")

        request = httpx_mock.get_request()
        assert "%24fields" in str(request.url) or "$fields" in str(request.url)

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

    async def test_get_merge_request_server_error(self, httpx_mock, space_client):
        httpx_mock.add_response(status_code=500)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await space_client.get_merge_request("ij", "ultimate", "123456")

        assert exc_info.value.response.status_code == 500

    async def test_get_merge_request_network_error(self, httpx_mock, space_client):
        httpx_mock.add_exception(httpx.ConnectError("Connection failed"))

        with pytest.raises(httpx.ConnectError):
            await space_client.get_merge_request("ij", "ultimate", "123456")


class TestGetMergeRequestDiscussions:
    """Tests for get_merge_request_discussions method."""

    async def test_get_discussions_success(self, httpx_mock, space_client, sample_review_with_channel, sample_feed_messages, sample_discussion_thread):
        # First call gets the review with feedChannel
        httpx_mock.add_response(json=sample_review_with_channel)
        # Second call gets feed messages
        httpx_mock.add_response(json=sample_feed_messages)
        # Third call gets the discussion thread
        httpx_mock.add_response(json=sample_discussion_thread)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        code_discussions = [r for r in result if r["type"] == "code_discussion"]
        assert len(code_discussions) == 1
        assert code_discussions[0]["file"] == "/src/auth.py"
        assert code_discussions[0]["line"] == 42
        assert len(code_discussions[0]["comments"]) == 2
        assert code_discussions[0]["comments"][0]["text"] == "Please add tests for this change"

    async def test_get_discussions_url_format(self, httpx_mock, space_client, sample_review_with_channel, sample_feed_messages, sample_discussion_thread):
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages)
        httpx_mock.add_response(json=sample_discussion_thread)

        await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        requests = httpx_mock.get_requests()
        assert len(requests) == 3
        # First request gets the review with feedChannel
        assert "code-reviews/number:123456" in str(requests[0].url)
        # Second and third requests get messages from chat channels
        assert "chats/messages" in str(requests[1].url)
        assert "chats/messages" in str(requests[2].url)

    async def test_get_discussions_code_discussion_structure(self, httpx_mock, space_client, sample_review_with_channel, sample_feed_messages, sample_discussion_thread):
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages)
        httpx_mock.add_response(json=sample_discussion_thread)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        assert isinstance(result, list)
        code_discussions = [r for r in result if r["type"] == "code_discussion"]
        for disc in code_discussions:
            assert "type" in disc
            assert "id" in disc
            assert "file" in disc
            assert "line" in disc
            assert "resolved" in disc
            assert "comments" in disc

    async def test_get_discussions_empty_feed(self, httpx_mock, space_client, sample_review_with_channel):
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json={"messages": []})

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        assert result == []

    async def test_get_discussions_no_channel(self, httpx_mock, space_client):
        # Review without feedChannel
        httpx_mock.add_response(json={})

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        assert result == []

    async def test_get_discussions_includes_general_messages(
        self, httpx_mock, space_client, sample_review_with_channel, sample_feed_messages_with_general, sample_discussion_thread
    ):
        """General timeline messages (non-code) should be included."""
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages_with_general)
        httpx_mock.add_response(json=sample_discussion_thread)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        code_discussions = [r for r in result if r["type"] == "code_discussion"]
        messages = [r for r in result if r["type"] == "message"]

        assert len(code_discussions) == 1
        assert len(messages) == 2

    async def test_get_discussions_general_message_structure(
        self, httpx_mock, space_client, sample_review_with_channel, sample_feed_messages_with_general, sample_discussion_thread
    ):
        """General messages should have text, author, and created fields."""
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages_with_general)
        httpx_mock.add_response(json=sample_discussion_thread)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        messages = [r for r in result if r["type"] == "message"]
        for msg in messages:
            assert "type" in msg
            assert "text" in msg
            assert "author" in msg
            assert "created" in msg

    async def test_get_discussions_app_messages_visible(
        self, httpx_mock, space_client, sample_review_with_channel, sample_feed_messages_with_general, sample_discussion_thread
    ):
        """Application/bot messages should be visible and have author_type='app'."""
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages_with_general)
        httpx_mock.add_response(json=sample_discussion_thread)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        messages = [r for r in result if r["type"] == "message"]
        app_msgs = [m for m in messages if m["author"].get("author_type") == "app"]
        assert len(app_msgs) == 1
        assert app_msgs[0]["event_class"] == "M2TextItemContent"

    async def test_get_discussions_messages_have_event_class(
        self, httpx_mock, space_client, sample_review_with_channel, sample_feed_messages_with_general, sample_discussion_thread
    ):
        """All messages should have an event_class field."""
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages_with_general)
        httpx_mock.add_response(json=sample_discussion_thread)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        messages = [r for r in result if r["type"] == "message"]
        for msg in messages:
            assert "event_class" in msg

    async def test_get_discussions_authors_have_type(
        self, httpx_mock, space_client, sample_review_with_channel, sample_feed_messages_with_general, sample_discussion_thread
    ):
        """All authors should have an author_type field."""
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages_with_general)
        httpx_mock.add_response(json=sample_discussion_thread)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        for item in result:
            if item["type"] == "message":
                assert "author_type" in item["author"]


class TestListMergeRequests:
    """Tests for list_merge_requests method."""

    async def test_list_merge_requests_success(self, httpx_mock, space_client, sample_merge_request_list):
        httpx_mock.add_response(json=sample_merge_request_list)

        result = await space_client.list_merge_requests("ij", "ultimate")

        assert len(result) == 2
        assert result[0]["id"] == "123456"

    async def test_list_merge_requests_url_format(self, httpx_mock, space_client, sample_merge_request_list):
        httpx_mock.add_response(json=sample_merge_request_list)

        await space_client.list_merge_requests("ij", "ultimate")

        request = httpx_mock.get_request()
        assert "projects/key:ij/code-reviews" in str(request.url)

    async def test_list_merge_requests_with_state_filter(self, httpx_mock, space_client, sample_merge_request_list):
        httpx_mock.add_response(json=sample_merge_request_list)

        await space_client.list_merge_requests("ij", "ultimate", state="Open")

        request = httpx_mock.get_request()
        # "Open" is mapped to "Opened" for the API
        assert "state=Opened" in str(request.url)

    async def test_list_merge_requests_filters_by_repository_client_side(self, httpx_mock, space_client):
        # Response includes MRs from multiple repositories (with review wrapper)
        # Note: repository is a string in the API response, not an object
        mixed_repos_response = {
            "data": [
                {
                    "review": {
                        "id": "123456",
                        "title": "MR in ultimate",
                        "state": "Opened",
                        "branchPairs": [{"sourceBranch": "feature/test", "targetBranch": "master", "repository": {"name": "ultimate"}}]
                    }
                },
                {
                    "review": {
                        "id": "789012",
                        "title": "MR in community",
                        "state": "Opened",
                        "branchPairs": [{"sourceBranch": "feature/other", "targetBranch": "master", "repository": {"name": "community"}}]
                    }
                }
            ]
        }
        httpx_mock.add_response(json=mixed_repos_response)

        result = await space_client.list_merge_requests("ij", "ultimate")

        # Should filter to only ultimate repository
        assert len(result) == 1
        assert result[0]["id"] == "123456"

        # Verify repository is NOT sent as query parameter (it's filtered client-side)
        request = httpx_mock.get_request()
        assert "repository=" not in str(request.url)

    async def test_list_merge_requests_with_branch_filter(self, httpx_mock, space_client, sample_merge_request_list):
        httpx_mock.add_response(json=sample_merge_request_list)

        result = await space_client.list_merge_requests("ij", "ultimate", branch="azhukova/fix-auth")

        # Client-side filtering should return only matching MR
        assert len(result) == 1
        assert result[0]["id"] == "123456"

    async def test_list_merge_requests_branch_filter_no_match(self, httpx_mock, space_client, sample_merge_request_list):
        httpx_mock.add_response(json=sample_merge_request_list)

        result = await space_client.list_merge_requests("ij", "ultimate", branch="nonexistent/branch")

        assert len(result) == 0

    async def test_list_merge_requests_with_custom_limit(self, httpx_mock, space_client, sample_merge_request_list):
        httpx_mock.add_response(json=sample_merge_request_list)

        await space_client.list_merge_requests("ij", "ultimate", limit=10)

        request = httpx_mock.get_request()
        # $top is URL-encoded as %24top
        assert "%24top=10" in str(request.url) or "$top=10" in str(request.url)

    async def test_list_merge_requests_empty(self, httpx_mock, space_client, empty_merge_request_list):
        httpx_mock.add_response(json=empty_merge_request_list)

        result = await space_client.list_merge_requests("ij", "ultimate")

        assert result == []


class TestFindMergeRequestByBranch:
    """Tests for find_merge_request_by_branch method."""

    async def test_find_mr_by_branch_found(self, httpx_mock, space_client, sample_merge_request_list, sample_merge_request):
        # First call: list_merge_requests
        httpx_mock.add_response(json=sample_merge_request_list)
        # Second call: get_merge_request for the found MR
        httpx_mock.add_response(json=sample_merge_request)

        result = await space_client.find_merge_request_by_branch("ij", "ultimate", "azhukova/fix-auth")

        assert result is not None
        assert result["id"] == "123456"

    async def test_find_mr_by_branch_not_found(self, httpx_mock, space_client, empty_merge_request_list):
        httpx_mock.add_response(json=empty_merge_request_list)

        result = await space_client.find_merge_request_by_branch("ij", "ultimate", "nonexistent/branch")

        assert result is None

    async def test_find_mr_by_branch_no_state_filter_by_default(self, httpx_mock, space_client, sample_merge_request_list, sample_merge_request):
        httpx_mock.add_response(json=sample_merge_request_list)
        httpx_mock.add_response(json=sample_merge_request)

        await space_client.find_merge_request_by_branch("ij", "ultimate", "azhukova/fix-auth")

        # Default: no state filter — searches all states
        requests = httpx_mock.get_requests()
        list_request = requests[0]
        assert "state=" not in str(list_request.url)

    async def test_find_mr_by_branch_with_state_filter(self, httpx_mock, space_client, sample_merge_request_list, sample_merge_request):
        httpx_mock.add_response(json=sample_merge_request_list)
        httpx_mock.add_response(json=sample_merge_request)

        await space_client.find_merge_request_by_branch("ij", "ultimate", "azhukova/fix-auth", state="Open")

        requests = httpx_mock.get_requests()
        list_request = requests[0]
        assert "state=Opened" in str(list_request.url)

    async def test_find_mr_by_branch_returns_first_match(self, httpx_mock, space_client, sample_merge_request):
        # List with multiple MRs matching the branch (with review wrapper)
        # Note: repository is a string in the API response
        multi_match_list = {
            "data": [
                {
                    "review": {
                        "id": "123456",
                        "title": "First MR",
                        "state": "Opened",
                        "branchPairs": [{"sourceBranch": "feature/test", "targetBranch": "main", "repository": {"name": "ultimate"}}]
                    }
                },
                {
                    "review": {
                        "id": "123457",
                        "title": "Second MR",
                        "state": "Opened",
                        "branchPairs": [{"sourceBranch": "feature/test", "targetBranch": "develop", "repository": {"name": "ultimate"}}]
                    }
                }
            ]
        }
        httpx_mock.add_response(json=multi_match_list)
        httpx_mock.add_response(json=sample_merge_request)

        result = await space_client.find_merge_request_by_branch("ij", "ultimate", "feature/test")

        # Should return the first match
        assert result["id"] == "123456"
