import json as _json
import re
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

    async def test_get_merge_request_resolves_author(
        self, httpx_mock, space_client, sample_merge_request, test_accounts
    ):
        httpx_mock.add_response(json=sample_merge_request)

        result = await space_client.get_merge_request("ij", "ultimate", "123456")

        assert isinstance(result.created_by, SpaceAccount)
        assert result.created_by.username == "azhukova"

    async def test_get_merge_request_resolves_participants(
        self, httpx_mock, space_client, sample_merge_request, test_accounts
    ):
        httpx_mock.add_response(json=sample_merge_request)

        result = await space_client.get_merge_request("ij", "ultimate", "123456")

        assert len(result.participants) == 1
        assert result.participants[0].user.username == "jdoe"
        assert result.participants[0].role.value == "Reviewer"

    async def test_get_merge_request_branch_pair(self, httpx_mock, space_client, sample_merge_request, test_accounts):
        httpx_mock.add_response(json=sample_merge_request)

        result = await space_client.get_merge_request("ij", "ultimate", "123456")

        assert result.branch_pair is not None
        assert result.branch_pair.source_branch == "azhukova/fix-auth"
        assert result.branch_pair.repository == "ultimate"

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

    async def test_get_discussions_code_discussion(
        self, httpx_mock, space_client, sample_review_with_channel, sample_feed_messages, sample_discussion_thread,
        test_accounts
    ):
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
        self,
        httpx_mock,
        space_client,
        sample_review_with_channel,
        sample_feed_messages_with_general,
        sample_discussion_thread,
        test_accounts,
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
        self,
        httpx_mock,
        space_client,
        sample_review_with_channel,
        sample_feed_messages_with_general,
        sample_discussion_thread,
        test_accounts,
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
        self,
        httpx_mock,
        space_client,
        sample_review_with_channel,
        sample_feed_messages_with_general,
        sample_discussion_thread,
        test_accounts,
    ):
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages_with_general)
        httpx_mock.add_response(json=sample_discussion_thread)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        messages = [r for r in result if isinstance(r, TimelineMessage)]
        for msg in messages:
            assert msg.event_class is not None


class TestDiscussionPagination:
    """Unit tests for the date-cursor pagination in discussions.py fetch_discussions."""

    _USER_PROFILE = {
        "id": "u1",
        "username": "user1",
        "name": {"firstName": "Test", "lastName": "User"},
        "emails": [],
    }

    def _make_msg(self, msg_id: str, time_ms: int, text: str = "msg") -> dict:
        return {
            "id": msg_id,
            "text": text,
            "time": time_ms,
            "author": {
                "name": "User", "details": {
                    "className": "CUserPrincipalDetails", "user": {"id": "u1", "username": "user1", "name": "User"}
                }
            },
            "details": {"className": "M2TextItemContent"},
            "attachments": [],
        }

    def _mock_user_profile(self, httpx_mock):
        """Mock the user profile resolution (called for each unique author)."""
        httpx_mock.add_response(
            url=re.compile(r".*/team-directory/profiles/.*"),
            json=self._USER_PROFILE,
            is_reusable=True,
        )

    async def test_fetches_multiple_pages(self, space_client, httpx_mock):
        self._mock_user_profile(httpx_mock)
        # Feed channel resolution
        httpx_mock.add_response(
            url=re.compile(r".*/code-reviews/.*"),
            json={"feedChannel": {"id": "chan-1"}},
        )
        # Page 1: 50 messages (full batch triggers pagination)
        page1_msgs = [self._make_msg(f"m{i}", 1700000000000 + i * 1000) for i in range(50)]
        httpx_mock.add_response(
            url=re.compile(r".*/chats/messages.*"),
            json={"messages": page1_msgs},
        )
        # Page 2: 10 messages (partial batch stops pagination)
        page2_msgs = [self._make_msg(f"m{50+i}", 1700000050000 + i * 1000) for i in range(10)]
        httpx_mock.add_response(
            url=re.compile(r".*/chats/messages.*"),
            json={"messages": page2_msgs},
        )

        result = await space_client.get_merge_request_discussions("proj", "repo", "42")
        messages = [r for r in result if isinstance(r, TimelineMessage)]
        assert len(messages) == 60

    async def test_single_page_no_extra_request(self, space_client, httpx_mock):
        self._mock_user_profile(httpx_mock)
        httpx_mock.add_response(
            url=re.compile(r".*/code-reviews/.*"),
            json={"feedChannel": {"id": "chan-1"}},
        )
        page1_msgs = [self._make_msg(f"m{i}", 1700000000000 + i * 1000) for i in range(10)]
        httpx_mock.add_response(
            url=re.compile(r".*/chats/messages.*"),
            json={"messages": page1_msgs},
        )

        result = await space_client.get_merge_request_discussions("proj", "repo", "42")
        messages = [r for r in result if isinstance(r, TimelineMessage)]
        assert len(messages) == 10

    async def test_empty_feed_returns_empty(self, space_client, httpx_mock):
        httpx_mock.add_response(
            url=re.compile(r".*/code-reviews/.*"),
            json={"feedChannel": {"id": "chan-1"}},
        )
        httpx_mock.add_response(
            url=re.compile(r".*/chats/messages.*"),
            json={"messages": []},
        )

        result = await space_client.get_merge_request_discussions("proj", "repo", "42")
        assert result == []


class TestListMergeRequests:

    async def test_list_merge_requests_success(
        self, httpx_mock, space_client, sample_merge_request_list, test_accounts
    ):
        httpx_mock.add_response(json=sample_merge_request_list)

        result = await space_client.list_merge_requests("ij", "ultimate", state="Open")

        assert len(result) == 2
        assert isinstance(result[0], MergeRequest)
        assert result[0].id == "123456"

    async def test_state_none_queries_all_states(self, httpx_mock, space_client, test_accounts):
        """state=None queries Opened, Closed, Merged separately and combines results."""
        open_mr = {
            "data": [{
                "review": {
                    "id": "open-1",
                    "number": 1,
                    "title": "Open MR",
                    "state": "Opened",
                    "createdAt": 1700000003000,
                    "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                    "branchPair": {"sourceBranch": "b1", "targetBranch": "main", "repository": {"name": "ultimate"}},
                }
            }]
        }
        closed_mr = {
            "data": [{
                "review": {
                    "id": "closed-1",
                    "number": 2,
                    "title": "Closed MR",
                    "state": "Closed",
                    "createdAt": 1700000002000,
                    "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                    "branchPair": {"sourceBranch": "b2", "targetBranch": "main", "repository": {"name": "ultimate"}},
                }
            }]
        }
        merged_mr = {
            "data": [{
                "review": {
                    "id": "merged-1",
                    "number": 3,
                    "title": "Merged MR",
                    "state": "Merged",
                    "createdAt": 1700000001000,
                    "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                    "branchPair": {"sourceBranch": "b3", "targetBranch": "main", "repository": {"name": "ultimate"}},
                }
            }]
        }
        httpx_mock.add_response(json=open_mr)
        httpx_mock.add_response(json=closed_mr)
        httpx_mock.add_response(json=merged_mr)

        result = await space_client.list_merge_requests("ij", "ultimate", state=None)

        assert len(result) == 3
        states = {mr.state for mr in result}
        assert MRState.OPENED in states
        assert MRState.CLOSED in states
        assert MRState.MERGED in states

    async def test_state_none_respects_limit(self, httpx_mock, space_client, test_accounts):
        """state=None stops early when limit is reached."""
        open_mrs = {
            "data": [{
                "review": {
                    "id": f"open-{i}",
                    "number": i,
                    "title": f"Open MR {i}",
                    "state": "Opened",
                    "createdAt": 1700000000000 + i * 1000,
                    "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                    "branchPair": {"sourceBranch": f"b{i}", "targetBranch": "main", "repository": {"name": "ultimate"}},
                }
            } for i in range(3)]
        }
        httpx_mock.add_response(json=open_mrs)

        result = await space_client.list_merge_requests("ij", "ultimate", state=None, limit=2)

        assert len(result) == 2

    async def test_state_none_sorted_by_created_at(self, httpx_mock, space_client, test_accounts):
        """state=None returns results sorted newest first."""
        old_mr = {
            "data": [{
                "review": {
                    "id": "old",
                    "number": 1,
                    "title": "Old",
                    "state": "Opened",
                    "createdAt": 1700000001000,
                    "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                    "branchPair": {"sourceBranch": "b1", "targetBranch": "main", "repository": {"name": "ultimate"}},
                }
            }]
        }
        new_mr = {
            "data": [{
                "review": {
                    "id": "new",
                    "number": 2,
                    "title": "New",
                    "state": "Closed",
                    "createdAt": 1700000009000,
                    "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                    "branchPair": {"sourceBranch": "b2", "targetBranch": "main", "repository": {"name": "ultimate"}},
                }
            }]
        }
        empty = {"data": []}
        httpx_mock.add_response(json=old_mr)
        httpx_mock.add_response(json=new_mr)
        httpx_mock.add_response(json=empty)

        result = await space_client.list_merge_requests("ij", "ultimate", state=None)

        assert len(result) == 2
        assert result[0].id == "new"  # newer first
        assert result[1].id == "old"

    async def test_list_merge_requests_with_state_filter(
        self, httpx_mock, space_client, sample_merge_request_list, test_accounts
    ):
        httpx_mock.add_response(json=sample_merge_request_list)

        await space_client.list_merge_requests("ij", "ultimate", state="Open")

        request = httpx_mock.get_request()
        assert "state=Opened" in str(request.url)

    async def test_list_merge_requests_filters_by_repository_client_side(self, httpx_mock, space_client, test_accounts):
        mixed_repos_response = {
            "data": [
                {
                    "review": {
                        "id": "123456", "title": "MR in ultimate", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova",
                                      "username": "azhukova"}, "branchPair": {
                                          "sourceBranch": "feature/test", "targetBranch": "master",
                                          "repository": {"name": "ultimate"}
                                      }
                    }
                },
                {
                    "review": {
                        "id": "789012", "title": "MR in community", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-jdoe", "name": "John Doe", "username": "jdoe"}, "branchPair": {
                            "sourceBranch": "feature/other", "targetBranch": "master",
                            "repository": {"name": "community"}
                        }
                    }
                },
            ]
        }
        httpx_mock.add_response(json=mixed_repos_response)

        result = await space_client.list_merge_requests("ij", "ultimate", state="Open")

        assert len(result) == 1
        assert result[0].id == "123456"

    async def test_list_merge_requests_with_branch_filter(
        self, httpx_mock, space_client, sample_merge_request_list, test_accounts
    ):
        httpx_mock.add_response(json=sample_merge_request_list)

        result = await space_client.list_merge_requests("ij", "ultimate", state="Open", branch="azhukova/fix-auth")

        assert len(result) == 1
        assert result[0].id == "123456"

    async def test_list_merge_requests_empty(self, httpx_mock, space_client, empty_merge_request_list):
        httpx_mock.add_response(json=empty_merge_request_list)

        result = await space_client.list_merge_requests("ij", "ultimate", state="Open")

        assert result == []

    async def test_list_merge_requests_with_author_filter(
        self, httpx_mock, space_client, sample_merge_request_list, test_accounts
    ):
        """author filter returns only MRs by that author."""
        httpx_mock.add_response(json=sample_merge_request_list)

        result = await space_client.list_merge_requests("ij", "ultimate", state="Open", author="azhukova")

        assert len(result) == 1
        assert result[0].id == "123456"
        assert result[0].created_by.username == "azhukova"

    async def test_author_filter_case_insensitive(
        self, httpx_mock, space_client, sample_merge_request_list, test_accounts
    ):
        """author filter is case-insensitive."""
        httpx_mock.add_response(json=sample_merge_request_list)

        result = await space_client.list_merge_requests("ij", "ultimate", state="Open", author="AZHUKOVA")

        assert len(result) == 1
        assert result[0].created_by.username == "azhukova"

    async def test_author_filter_skips_null_created_by(self, httpx_mock, space_client, test_accounts):
        """MR with createdBy: null is skipped, no crash."""
        response = {
            "data": [
                {
                    "review": {
                        "id": "100", "title": "No author", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": None, "branchPair": {
                            "sourceBranch": "feature/x", "targetBranch": "main", "repository": {"name": "ultimate"}
                        }
                    }
                },
                {
                    "review": {
                        "id": "200", "title": "Has author", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                        "branchPair": {
                            "sourceBranch": "feature/y", "targetBranch": "main", "repository": {"name": "ultimate"}
                        }
                    }
                },
            ]
        }
        httpx_mock.add_response(json=response)

        result = await space_client.list_merge_requests("ij", "ultimate", state="Open", author="azhukova")

        assert len(result) == 1
        assert result[0].id == "200"

    async def test_author_filter_no_matches_returns_empty(
        self, httpx_mock, space_client, sample_merge_request_list, test_accounts
    ):
        """Author matches nobody → empty result (no crash, no infinite loop)."""
        httpx_mock.add_response(json=sample_merge_request_list)

        result = await space_client.list_merge_requests("ij", "ultimate", state="Open", author="nonexistent")

        assert result == []

    async def test_paginates_when_filtering_by_author(self, httpx_mock, space_client, test_accounts, monkeypatch):
        """First page has no author matches, second page has one."""
        import space.pagination
        monkeypatch.setattr(space.pagination, "_PAGE_SIZE", 2)

        page1 = {
            "data": [
                {
                    "review": {
                        "id": "100", "title": "By jdoe 1", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-jdoe", "name": "John Doe", "username": "jdoe"}, "branchPair": {
                            "sourceBranch": "jdoe/feature1", "targetBranch": "main", "repository": {"name": "ultimate"}
                        }
                    }
                },
                {
                    "review": {
                        "id": "101", "title": "By jdoe 2", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-jdoe", "name": "John Doe", "username": "jdoe"}, "branchPair": {
                            "sourceBranch": "jdoe/feature2", "targetBranch": "main", "repository": {"name": "ultimate"}
                        }
                    }
                },
            ]
        }
        page2 = {
            "data": [
                {
                    "review": {
                        "id": "101", "title": "By jdoe 2", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-jdoe", "name": "John Doe", "username": "jdoe"}, "branchPair": {
                            "sourceBranch": "jdoe/feature2", "targetBranch": "main", "repository": {"name": "ultimate"}
                        }
                    }
                },
                {
                    "review": {
                        "id": "200", "title": "By azhukova", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                        "branchPair": {
                            "sourceBranch": "azhukova/fix", "targetBranch": "main", "repository": {"name": "ultimate"}
                        }
                    }
                },
            ]
        }
        page3 = {
            "data": [
                {
                    "review": {
                        "id": "200", "title": "By azhukova", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                        "branchPair": {
                            "sourceBranch": "azhukova/fix", "targetBranch": "main", "repository": {"name": "ultimate"}
                        }
                    }
                },
            ]
        }
        httpx_mock.add_response(json=page1)
        httpx_mock.add_response(json=page2)
        httpx_mock.add_response(json=page3)

        result = await space_client.list_merge_requests("ij", "ultimate", state="Open", author="azhukova")

        assert len(result) == 1
        assert result[0].id == "200"

    async def test_paginates_when_filtering_by_branch(self, httpx_mock, space_client, test_accounts, monkeypatch):
        """First page has no branch matches, second page has a match."""
        import space.pagination
        monkeypatch.setattr(space.pagination, "_PAGE_SIZE", 2)

        page1 = {
            "data": [
                {
                    "review": {
                        "id": "100", "title": "Unrelated 1", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                        "branchPair": {
                            "sourceBranch": "other/branch", "targetBranch": "main", "repository": {"name": "ultimate"}
                        }
                    }
                },
                {
                    "review": {
                        "id": "101", "title": "Unrelated 2", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                        "branchPair": {
                            "sourceBranch": "other/branch2", "targetBranch": "main", "repository": {"name": "ultimate"}
                        }
                    }
                },
            ]
        }
        # Page 2 overlaps by 1 (item 101), then has the target
        page2 = {
            "data": [
                {
                    "review": {
                        "id": "101", "title": "Unrelated 2", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                        "branchPair": {
                            "sourceBranch": "other/branch2", "targetBranch": "main", "repository": {"name": "ultimate"}
                        }
                    }
                },
                {
                    "review": {
                        "id": "200", "title": "Target MR", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova",
                                      "username": "azhukova"}, "branchPair": {
                                          "sourceBranch": "azhukova/fix-auth", "targetBranch": "main",
                                          "repository": {"name": "ultimate"}
                                      }
                    }
                },
            ]
        }
        # Page 3 is partial (signals end)
        page3 = {
            "data": [
                {
                    "review": {
                        "id": "200", "title": "Target MR", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova",
                                      "username": "azhukova"}, "branchPair": {
                                          "sourceBranch": "azhukova/fix-auth", "targetBranch": "main",
                                          "repository": {"name": "ultimate"}
                                      }
                    }
                },
            ]
        }
        httpx_mock.add_response(json=page1)
        httpx_mock.add_response(json=page2)
        httpx_mock.add_response(json=page3)

        result = await space_client.list_merge_requests("ij", "ultimate", state="Open", branch="azhukova/fix-auth")

        assert len(result) == 1
        assert result[0].id == "200"

    async def test_paginates_when_filtering_by_repository(self, httpx_mock, space_client, test_accounts, monkeypatch):
        """First page has wrong repo, second page has right repo."""
        import space.pagination
        monkeypatch.setattr(space.pagination, "_PAGE_SIZE", 2)

        page1 = {
            "data": [
                {
                    "review": {
                        "id": "100", "title": "Wrong repo 1", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                        "branchPair": {
                            "sourceBranch": "feature/x", "targetBranch": "main", "repository": {"name": "community"}
                        }
                    }
                },
                {
                    "review": {
                        "id": "101", "title": "Wrong repo 2", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                        "branchPair": {
                            "sourceBranch": "feature/z", "targetBranch": "main", "repository": {"name": "community"}
                        }
                    }
                },
            ]
        }
        page2 = {
            "data": [
                {
                    "review": {
                        "id": "101", "title": "Wrong repo 2", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                        "branchPair": {
                            "sourceBranch": "feature/z", "targetBranch": "main", "repository": {"name": "community"}
                        }
                    }
                },
                {
                    "review": {
                        "id": "200", "title": "Right repo", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                        "branchPair": {
                            "sourceBranch": "feature/y", "targetBranch": "main", "repository": {"name": "ultimate"}
                        }
                    }
                },
            ]
        }
        page3 = {
            "data": [
                {
                    "review": {
                        "id": "200", "title": "Right repo", "state": "Opened", "createdAt": 1736937000000,
                        "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                        "branchPair": {
                            "sourceBranch": "feature/y", "targetBranch": "main", "repository": {"name": "ultimate"}
                        }
                    }
                },
            ]
        }
        httpx_mock.add_response(json=page1)
        httpx_mock.add_response(json=page2)
        httpx_mock.add_response(json=page3)

        result = await space_client.list_merge_requests("ij", "ultimate", state="Open")

        assert len(result) == 1
        assert result[0].id == "200"

    async def test_no_text_derived_from_branch(
        self, httpx_mock, space_client, sample_merge_request_list, test_accounts
    ):
        """branch parameter must NOT cause text param in API request."""
        httpx_mock.add_response(json=sample_merge_request_list)

        await space_client.list_merge_requests("ij", "ultimate", state="Open", branch="azhukova/fix-auth")

        request = httpx_mock.get_request()
        params = parse_qs(urlparse(str(request.url)).query)
        assert "text" not in params

    async def test_explicit_text_passed_through(
        self, httpx_mock, space_client, sample_merge_request_list, test_accounts
    ):
        """Explicit text parameter is passed to API."""
        httpx_mock.add_response(json=sample_merge_request_list)

        await space_client.list_merge_requests("ij", "ultimate", state="Open", text="search term")

        request = httpx_mock.get_request()
        params = parse_qs(urlparse(str(request.url)).query)
        assert params["text"] == ["search term"]


class TestFindMergeRequestByBranch:

    async def test_find_mr_by_branch_found(
        self, httpx_mock, space_client, sample_merge_request_list, sample_merge_request, test_accounts
    ):
        httpx_mock.add_response(json=sample_merge_request_list)
        httpx_mock.add_response(json=sample_merge_request)

        result = await space_client.find_merge_request_by_branch("ij", "ultimate", "azhukova/fix-auth", state="Open")

        assert result is not None
        assert result.id == "123456"

    async def test_find_mr_by_branch_not_found(self, httpx_mock, space_client, empty_merge_request_list):
        # 6 empty responses: 3 states x text-search + 3 states x full-scan fallback
        for _ in range(6):
            httpx_mock.add_response(json=empty_merge_request_list)

        result = await space_client.find_merge_request_by_branch("ij", "ultimate", "nonexistent/branch")

        assert result is None

    async def test_find_mr_fast_path_with_text(self, space_client, test_accounts):
        """Text search finds the MR on first call — only 1 list call made."""
        mr = MergeRequest(
            id="123456",
            number=188120,
            title="Fix auth",
            state=MRState.OPENED,
            created_at=None,
            description=None,
            created_by=SpaceAccount(
                id="user-azhukova", username="azhukova", email="a@test.com", first_name="Anna", last_name="Zhukova"
            ),
            participants=(),
            branch_pair=BranchPair(source_branch="azhukova/fix-auth", target_branch="main", repository="ultimate"),
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
            id="123456",
            number=188120,
            title="Fix auth",
            state=MRState.OPENED,
            created_at=None,
            description=None,
            created_by=SpaceAccount(
                id="user-azhukova", username="azhukova", email="a@test.com", first_name="Anna", last_name="Zhukova"
            ),
            participants=(),
            branch_pair=BranchPair(source_branch="azhukova/fix-auth", target_branch="main", repository="ultimate"),
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
            "ij",
            "ultimate",
            "azhukova/new-feature",
            "master",
            "New feature",
        )

        assert isinstance(result, MergeRequest)
        assert result.number == 194200
        assert result.title == "New feature"

    async def test_create_mr_request_body(self, httpx_mock, space_client, sample_created_merge_request):
        httpx_mock.add_response(json=sample_created_merge_request, status_code=200)

        await space_client.create_merge_request(
            "ij",
            "ultimate",
            "azhukova/new-feature",
            "master",
            "New feature",
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
                "ij",
                "ultimate",
                "nonexistent",
                "master",
                "Test",
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
        httpx_mock.add_response(
            json={"id": "2eTFJg4dJrmL", "number": 190592, "title": "T", "state": "Opened", "createdAt": 1736937000000}
        )
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
        self,
        httpx_mock,
        space_client,
        sample_review_with_channel,
        sample_feed_messages_with_attachments,
        test_accounts,
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
        self,
        httpx_mock,
        space_client,
        sample_review_with_channel,
        sample_feed_messages_with_attachments,
        test_accounts,
    ):
        httpx_mock.add_response(json=sample_review_with_channel)
        httpx_mock.add_response(json=sample_feed_messages_with_attachments)

        result = await space_client.get_merge_request_discussions("ij", "ultimate", "123456")

        messages = [r for r in result if isinstance(r, TimelineMessage)]
        # Second message has only an UnfurlAttachment — empty tuple
        msg_unfurl_only = messages[1]
        assert msg_unfurl_only.attachments == ()

    async def test_thread_replies_include_attachments(
        self,
        httpx_mock,
        space_client,
        sample_review_with_channel,
        sample_feed_messages,
        sample_discussion_thread_with_attachments,
        test_accounts,
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

    # User token tests -------------------------------------------------------------------------------------------------

    async def test_valid_user_token_returns_profile_with_kind(self, httpx_mock):
        httpx_mock.add_response(json={
            "username": "azhukova",
            "emails": [{"email": "anna@jetbrains.com"}],
        })
        result = await validate_token("good-token")
        assert result["kind"] == "user"
        assert result["username"] == "azhukova"
        assert result["emails"][0]["email"] == "anna@jetbrains.com"

    async def test_user_token_requests_correct_url_and_fields(self, httpx_mock):
        httpx_mock.add_response(json={"username": "x", "emails": []})
        await validate_token("tok")
        request = httpx_mock.get_request()
        assert "team-directory/profiles/me" in str(request.url)
        assert "username" in str(request.url)
        assert "name" in str(request.url)
        assert "emails" in str(request.url)

    # App token fallback tests -----------------------------------------------------------------------------------------

    async def test_app_token_returns_on_user_403(self, httpx_mock):
        httpx_mock.add_response(url=re.compile(r".*/profiles/me.*"), status_code=403)
        httpx_mock.add_response(
            url=re.compile(r".*/applications/me.*"),
            json={"name": "my-app"},
        )
        result = await validate_token("app-token")
        assert result["kind"] == "app"
        assert result["name"] == "my-app"

    async def test_app_token_requests_correct_url(self, httpx_mock):
        httpx_mock.add_response(url=re.compile(r".*/profiles/me.*"), status_code=403)
        httpx_mock.add_response(
            url=re.compile(r".*/applications/me.*"),
            json={"name": "test-app"},
        )
        await validate_token("app-token")
        requests = httpx_mock.get_requests()
        assert len(requests) == 2
        assert "applications/me" in str(requests[1].url)
        assert "name" in str(requests[1].url)

    # Error handling tests ---------------------------------------------------------------------------------------------

    async def test_401_does_not_try_app_endpoint(self, httpx_mock):
        httpx_mock.add_response(status_code=401)
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await validate_token("bad-token")
        assert exc_info.value.response.status_code == 401
        assert len(httpx_mock.get_requests()) == 1

    async def test_500_does_not_try_app_endpoint(self, httpx_mock):
        httpx_mock.add_response(status_code=500)
        with pytest.raises(httpx.HTTPStatusError):
            await validate_token("tok")
        assert len(httpx_mock.get_requests()) == 1

    async def test_403_from_both_endpoints_raises(self, httpx_mock):
        httpx_mock.add_response(url=re.compile(r".*/profiles/me.*"), status_code=403)
        httpx_mock.add_response(url=re.compile(r".*/applications/me.*"), status_code=403)
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await validate_token("bad-token")
        assert exc_info.value.response.status_code == 403


# Comment / discussion methods =========================================================================================


class TestGetFeedChannel:

    async def test_returns_channel_id(self, space_client, httpx_mock):
        httpx_mock.add_response(json={"feedChannel": {"id": "chan-123"}})
        result = await space_client.get_feed_channel("proj", "42")
        assert result == "chan-123"

    async def test_uses_number_prefix_for_numeric_id(self, space_client, httpx_mock):
        httpx_mock.add_response(json={"feedChannel": {"id": "c"}})
        await space_client.get_feed_channel("proj", "42")
        request = httpx_mock.get_request()
        assert "/code-reviews/number:42" in str(request.url)

    async def test_uses_id_prefix_for_non_numeric(self, space_client, httpx_mock):
        httpx_mock.add_response(json={"feedChannel": {"id": "c"}})
        await space_client.get_feed_channel("proj", "abc-123")
        request = httpx_mock.get_request()
        assert "/code-reviews/id:abc-123" in str(request.url)

    async def test_returns_none_when_no_channel(self, space_client, httpx_mock):
        httpx_mock.add_response(json={})
        result = await space_client.get_feed_channel("proj", "42")
        assert result is None

    async def test_raises_on_404(self, space_client, httpx_mock):
        httpx_mock.add_response(status_code=404)
        with pytest.raises(httpx.HTTPStatusError):
            await space_client.get_feed_channel("proj", "999")


class TestPostComment:

    async def test_posts_to_feed_channel(self, space_client, httpx_mock):
        httpx_mock.add_response(
            url=re.compile(r".*/code-reviews/.*"),
            json={"feedChannel": {"id": "chan-1"}},
        )
        httpx_mock.add_response(
            url=re.compile(r".*/send-message.*"),
            json={"id": "msg-1"},
        )
        result = await space_client.post_comment("proj", "42", "hello")
        assert result == "msg-1"
        requests = httpx_mock.get_requests()
        assert len(requests) == 2
        body = requests[1].read()
        parsed = _json.loads(body)
        assert parsed["channel"] == "id:chan-1"
        assert parsed["content"]["text"] == "hello"
        assert parsed["content"]["className"] == "ChatMessage.Text"

    async def test_thread_reply_includes_thread_id(self, space_client, httpx_mock):
        httpx_mock.add_response(
            url=re.compile(r".*/code-reviews/.*"),
            json={"feedChannel": {"id": "chan-1"}},
        )
        httpx_mock.add_response(
            url=re.compile(r".*/send-message.*"),
            json={"id": "msg-2"},
        )
        await space_client.post_comment("proj", "42", "reply", thread_message_id="msg-1")
        body = _json.loads(httpx_mock.get_requests()[1].read())
        assert body["thread"] == "id:msg-1"

    async def test_no_thread_field_without_thread_id(self, space_client, httpx_mock):
        httpx_mock.add_response(
            url=re.compile(r".*/code-reviews/.*"),
            json={"feedChannel": {"id": "chan-1"}},
        )
        httpx_mock.add_response(
            url=re.compile(r".*/send-message.*"),
            json={"id": "msg-1"},
        )
        await space_client.post_comment("proj", "42", "hello")
        body = _json.loads(httpx_mock.get_requests()[1].read())
        assert "thread" not in body

    async def test_raises_when_no_feed_channel(self, space_client, httpx_mock):
        httpx_mock.add_response(json={})
        with pytest.raises(ValueError, match="feed channel"):
            await space_client.post_comment("proj", "42", "hello")

    async def test_raises_on_404_review(self, space_client, httpx_mock):
        httpx_mock.add_response(status_code=404)
        with pytest.raises(httpx.HTTPStatusError):
            await space_client.post_comment("proj", "999", "hello")


class TestCreateCodeDiscussion:

    async def test_creates_discussion_with_anchor(self, space_client, httpx_mock):
        httpx_mock.add_response(json={"channel": {"id": "disc-chan-1"}})
        result = await space_client.create_code_discussion(
            "proj",
            "42",
            "my-repo",
            "abc123",
            "src/main.py",
            15,
            "Fix this",
        )
        assert result == "disc-chan-1"
        body = _json.loads(httpx_mock.get_request().read())
        assert body["text"] == "Fix this"
        assert body["repository"] == "my-repo"
        assert body["reviewId"] == "number:42"
        assert body["anchor"]["revision"] == "abc123"
        assert body["anchor"]["filename"] == "src/main.py"
        assert body["anchor"]["line"] == 15
        assert body["pending"] is False

    async def test_uses_id_prefix_for_non_numeric_review(self, space_client, httpx_mock):
        httpx_mock.add_response(json={"channel": {"id": "c"}})
        await space_client.create_code_discussion(
            "proj",
            "abc-id",
            "repo",
            "sha",
            "f.py",
            1,
            "text",
        )
        body = _json.loads(httpx_mock.get_request().read())
        assert body["reviewId"] == "id:abc-id"

    async def test_url_uses_project_key(self, space_client, httpx_mock):
        httpx_mock.add_response(json={"channel": {"id": "c"}})
        await space_client.create_code_discussion(
            "my-proj",
            "1",
            "repo",
            "sha",
            "f.py",
            1,
            "text",
        )
        request = httpx_mock.get_request()
        assert "/projects/key:my-proj/code-reviews/code-discussions" in str(request.url)

    async def test_raises_on_error(self, space_client, httpx_mock):
        httpx_mock.add_response(status_code=403)
        with pytest.raises(httpx.HTTPStatusError):
            await space_client.create_code_discussion(
                "proj",
                "42",
                "repo",
                "sha",
                "f.py",
                1,
                "text",
            )


class TestReplyToDiscussion:

    async def test_posts_to_discussion_channel(self, space_client, httpx_mock):
        httpx_mock.add_response(json={"id": "reply-1"})
        await space_client.reply_to_discussion("disc-chan-1", "my reply")
        body = _json.loads(httpx_mock.get_request().read())
        assert body["channel"] == "id:disc-chan-1"
        assert body["content"]["text"] == "my reply"

    async def test_raises_on_error(self, space_client, httpx_mock):
        httpx_mock.add_response(status_code=403)
        with pytest.raises(httpx.HTTPStatusError):
            await space_client.reply_to_discussion("chan", "text")
