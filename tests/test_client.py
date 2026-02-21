import pytest
import httpx

from space_mcp.client import SpaceClient


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

        assert len(result) == 1
        assert result[0]["file"] == "/src/auth.py"
        assert result[0]["line"] == 42
        assert len(result[0]["comments"]) == 2
        assert result[0]["comments"][0]["text"] == "Please add tests for this change"

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

    async def test_get_discussions_returns_list(self, httpx_mock, space_client, sample_review_with_channel, sample_feed_messages, sample_discussion_thread):
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages)
        httpx_mock.add_response(json=sample_discussion_thread)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        assert isinstance(result, list)
        # Verify transformed structure
        for disc in result:
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

    async def test_find_mr_by_branch_uses_open_state(self, httpx_mock, space_client, sample_merge_request_list, sample_merge_request):
        httpx_mock.add_response(json=sample_merge_request_list)
        httpx_mock.add_response(json=sample_merge_request)

        await space_client.find_merge_request_by_branch("ij", "ultimate", "azhukova/fix-auth")

        # Verify the list request used state=Opened (mapped from Open)
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
