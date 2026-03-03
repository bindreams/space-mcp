import os

import pytest

from space.client import SpaceClient
from space.patronus import PatronusClient


# Fixtures for unit tests (fake base URL, no real API calls) =================


@pytest.fixture
def space_client():
    """Create a SpaceClient instance with test token."""
    return SpaceClient(token="test-token")


@pytest.fixture
def sample_merge_request():
    """Sample merge request response from Space API."""
    return {
        "id": "123456",
        "number": 188120,
        "title": "Fix authentication bug",
        "description": None,
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


@pytest.fixture
def sample_feed_messages_with_general():
    """Sample feed messages with both code discussions and general messages."""
    return {
        "messages": [
            {
                "id": "feed-msg-1",
                "text": "posted a comment",
                "author": {
                    "name": "John.Doe",
                    "details": {
                        "user": {
                            "username": "jdoe",
                            "name": {"firstName": "John", "lastName": "Doe"},
                        }
                    },
                },
                "time": 1705315200000,
                "details": {
                    "className": "CodeDiscussionAddedFeedEvent",
                    "codeDiscussion": {
                        "id": "disc-1",
                        "resolved": False,
                        "channel": {"id": "disc-channel-1"},
                        "anchor": {"filename": "/src/auth.py", "line": 42},
                    },
                },
            },
            {
                "id": "feed-msg-2",
                "text": "Someone started dry run",
                "author": {
                    "name": "Anna.Zhukova",
                    "details": {
                        "className": "CUserPrincipalDetails",
                        "user": {
                            "username": "azhukova",
                            "name": {"firstName": "Anna", "lastName": "Zhukova"},
                        },
                    },
                },
                "time": 1705320000000,
                "details": {"className": "MCMessage"},
            },
            {
                "id": "feed-msg-3",
                "text": "Merge Dry Run \"Fix auth\" succeeded\nhttps://patronus.labs.jb.gg/robot/abc-123",
                "author": {
                    "name": "Patronus",
                    "details": {
                        "className": "CApplicationPrincipalDetails",
                    },
                },
                "time": 1705323600000,
                "details": {"className": "M2TextItemContent"},
            },
        ]
    }


# Patronus fixtures ==========================================================


@pytest.fixture
def patronus_client():
    """Create a PatronusClient instance with test token."""
    return PatronusClient(token="test-token")


@pytest.fixture
def sample_robot_overview():
    """Sample Patronus robot overview response."""
    return {
        "name": "Fix auth (dry run)",
        "id": "cc448634-880e-411f-9ee6-347e9a6087ac",
        "repository": "ultimate",
        "sourceBranch": "refs/patronus/safepush/fe9f53cbda72427089a6f095c926bbce",
        "targetBranch": "master",
        "startDateTime": "2026-01-15T08:00:02.120774Z",
        "finishDateTime": "2026-01-15T08:08:08.042915Z",
        "status": "SUCCESSFUL",
        "type": "SAFE_PUSH",
        "pushMode": "DRY_RUN",
        "cancellationReason": None,
        "owner": {
            "type": "USER",
            "id": "CA0CB9DE-9B5F-44F4-9EF3-38A1A35317E9",
            "name": "Anna Zhukova",
            "email": "anna.zhukova@jetbrains.com",
        },
        "options": {},
    }


@pytest.fixture
def sample_robots_list(sample_robot_overview):
    """Sample Patronus robots list response."""
    return {
        "me": {
            "type": "USER",
            "id": "CA0CB9DE-9B5F-44F4-9EF3-38A1A35317E9",
            "name": "Anna Zhukova",
            "email": "anna.zhukova@jetbrains.com",
        },
        "robots": [sample_robot_overview],
        "start": "2026-01-14T00:00:00Z",
        "end": "2026-01-16T00:00:00Z",
    }


@pytest.fixture
def sample_teamcity_checks_response():
    """Sample raw Patronus TeamCity checks API response (wrapped in object)."""
    return {
        "robotId": "cc448634-880e-411f-9ee6-347e9a6087ac",
        "teamCityChecks": [
            {
                "name": "Compile All",
                "status": "SUCCESS",
                "buildId": 98765,
                "buildConfigurationUrl": "https://buildserver.labs.intellij.net/buildConfiguration/compile",
                "attempts": [{"id": "attempt-1", "status": "SUCCESS", "buildId": 98765}],
            },
            {
                "name": "Unit Tests",
                "status": "FAILURE",
                "buildId": 98770,
                "buildConfigurationUrl": "https://buildserver.labs.intellij.net/buildConfiguration/test_Build",
                "attempts": [{"id": "attempt-fail-1", "status": "FAILURE", "buildId": 98770}],
            },
        ],
    }


@pytest.fixture
def sample_teamcity_checks(sample_teamcity_checks_response):
    """The extracted list of TeamCity checks (what PatronusClient.get_robot_teamcity_checks returns)."""
    return sample_teamcity_checks_response["teamCityChecks"]


@pytest.fixture
def sample_robot_problems():
    """Sample Patronus robot problems response."""
    return {
        "robotId": "cc448634-880e-411f-9ee6-347e9a6087ac",
        "problems": [
            {
                "title": "3 tests failed in Unit Tests",
                "detailsMarkdown": "Failures in `com.example.FooTest`",
            }
        ],
    }


@pytest.fixture
def sample_attempt_details():
    """Sample Patronus TeamCity check attempt details response."""
    return {
        "id": "attempt-fail-1",
        "number": 0,
        "buildId": "98770",
        "buildUrl": "https://buildserver.labs.intellij.net/build/98770",
        "startedAt": "2026-01-15T08:00:06Z",
        "finishedAt": "2026-01-15T08:07:28Z",
        "status": "FAILURE",
        "failedTestsNumber": 1,
        "failedBuildsNumber": 1,
        "failedToStartBuildsNumber": 0,
        "failedTests": [
            {
                "name": "com.example.FooTest.test something important",
                "url": "https://buildserver.labs.intellij.net/test/123",
            }
        ],
        "failedBuilds": [
            {
                "buildId": "98770",
                "buildUrl": "https://buildserver.labs.intellij.net/build/98770",
                "buildConfigurationId": "test_Build",
                "buildConfigurationUrl": "https://buildserver.labs.intellij.net/buildConfiguration/test_Build",
                "buildConfigurationName": "Unit Tests",
                "fullProjectName": "Project / Tests",
                "isFailedToStart": False,
                "problems": [
                    {"details": "Process exited with code 1 (Step: test)"},
                    {"details": "1 failed test detected"},
                ],
            }
        ],
    }


# Fixtures for integration tests (real API calls, loaded from .env) ==========


@pytest.fixture
def space_token():
    """Get SPACE_TOKEN from environment (loaded from .env by pytest-dotenv)."""
    token = os.environ.get("SPACE_TOKEN")
    if not token:
        pytest.skip("SPACE_TOKEN not set")
    return token


@pytest.fixture
def real_client(space_token):
    """Create a SpaceClient with real token for integration tests."""
    return SpaceClient(token=space_token)


@pytest.fixture
def real_patronus_client(space_token):
    """Create a PatronusClient with real token for integration tests."""
    return PatronusClient(token=space_token)
