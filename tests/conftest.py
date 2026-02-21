import pytest

from space_mcp.client import SpaceClient


@pytest.fixture
def space_client():
    """Create a SpaceClient instance with test token."""
    return SpaceClient(token="test-token", base_url="https://test.jetbrains.team")


@pytest.fixture
def sample_merge_request():
    """Sample merge request response from Space API."""
    return {
        "id": "123456",
        "title": "Fix authentication bug",
        "state": "Opened",
        "createdBy": {
            "name": "Anna Zhukova",
            "username": "azhukova"
        },
        "createdAt": "2026-01-15T10:30:00Z",
        "participants": [
            {
                "user": {"name": "John Doe", "username": "jdoe"},
                "role": "Reviewer",
                "state": "Pending"
            }
        ],
        "branchPairs": [
            {
                "sourceBranch": "azhukova/fix-auth",
                "targetBranch": "main",
                "repository": {"name": "ultimate"}
            }
        ],
        "feedChannel": {
            "id": "test-channel-id"
        }
    }


@pytest.fixture
def sample_review_with_channel():
    """Sample review response with just feedChannel for discussions lookup."""
    return {
        "feedChannel": {
            "id": "test-channel-id"
        }
    }


@pytest.fixture
def sample_feed_messages():
    """Sample feed messages with code discussion events."""
    return {
        "messages": [
            {
                "id": "feed-msg-1",
                "text": "posted a comment",
                "author": {"name": "John.Doe"},
                "details": {
                    "className": "CodeDiscussionAddedFeedEvent",
                    "codeDiscussion": {
                        "id": "disc-1",
                        "resolved": False,
                        "channel": {"id": "disc-channel-1"},
                        "anchor": {
                            "filename": "/src/auth.py",
                            "line": 42
                        }
                    }
                }
            }
        ]
    }


@pytest.fixture
def sample_discussion_thread():
    """Sample discussion thread messages."""
    return {
        "messages": [
            {
                "id": "thread-msg-1",
                "text": "Please add tests for this change",
                "author": {
                    "name": "John.Doe",
                    "details": {
                        "user": {
                            "username": "jdoe",
                            "name": {"firstName": "John", "lastName": "Doe"}
                        }
                    }
                },
                "time": 1705315200000
            },
            {
                "id": "thread-msg-2",
                "text": "Done, added unit tests",
                "author": {
                    "name": "Anna.Zhukova",
                    "details": {
                        "user": {
                            "username": "azhukova",
                            "name": {"firstName": "Anna", "lastName": "Zhukova"}
                        }
                    }
                },
                "time": 1705318800000
            }
        ]
    }


@pytest.fixture
def sample_merge_request_list():
    """Sample list of merge requests from Space API."""
    return {
        "data": [
            {
                "review": {
                    "id": "123456",
                    "title": "Fix authentication bug",
                    "state": "Opened",
                    "createdBy": {"name": "Anna Zhukova", "username": "azhukova"},
                    "createdAt": "2026-01-15T10:30:00Z",
                    "branchPairs": [
                        {"sourceBranch": "azhukova/fix-auth", "targetBranch": "main", "repository": {"name": "ultimate"}}
                    ]
                }
            },
            {
                "review": {
                    "id": "123457",
                    "title": "Update dependencies",
                    "state": "Opened",
                    "createdBy": {"name": "John Doe", "username": "jdoe"},
                    "createdAt": "2026-01-14T09:00:00Z",
                    "branchPairs": [
                        {"sourceBranch": "jdoe/update-deps", "targetBranch": "main", "repository": {"name": "ultimate"}}
                    ]
                }
            }
        ]
    }


@pytest.fixture
def empty_merge_request_list():
    """Empty merge request list response."""
    return {"data": []}
