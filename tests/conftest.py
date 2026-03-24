import os

import pytest

from space.client import SpaceClient
from space.models import SpaceAccount
from space.patronus import PatronusClient


# SpaceAccount cache management =====


@pytest.fixture(autouse=True)
def _clear_space_account_cache():
    """Clear SpaceAccount cache before each test to avoid cross-test leaks."""
    SpaceAccount.clear_cache()
    yield
    SpaceAccount.clear_cache()


def _prepopulate_accounts() -> dict[str, SpaceAccount]:
    """Pre-populate SpaceAccount cache with test accounts.

    Returns a dict of id -> SpaceAccount for reference.
    """
    accounts = [
        SpaceAccount(id="user-azhukova", username="azhukova", email="anna@test.com", first_name="Anna", last_name="Zhukova"),
        SpaceAccount(id="user-jdoe", username="jdoe", email="john@test.com", first_name="John", last_name="Doe"),
    ]
    for a in accounts:
        SpaceAccount._cache_by_id[a.id] = a
        SpaceAccount._cache_by_username[a.username] = a
    return {a.id: a for a in accounts}


@pytest.fixture
def test_accounts():
    """Pre-populate SpaceAccount cache and return the test accounts."""
    return _prepopulate_accounts()


# Fixtures for unit tests (fake base URL, no real API calls) =====


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
            "id": "user-azhukova",
            "name": "Anna Zhukova",
            "username": "azhukova",
        },
        "createdAt": 1736937000000,
        "participants": [
            {
                "user": {"id": "user-jdoe", "name": "John Doe", "username": "jdoe"},
                "role": "Reviewer",
                "state": "Pending",
            }
        ],
        "branchPairs": [
            {
                "sourceBranch": "azhukova/fix-auth",
                "targetBranch": "main",
                "repository": {"name": "ultimate"},
            }
        ],
        "feedChannel": {
            "id": "test-channel-id",
        },
    }


@pytest.fixture
def sample_review_with_channel():
    """Sample review response with just feedChannel for discussions lookup."""
    return {
        "feedChannel": {
            "id": "test-channel-id",
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
                            "line": 42,
                        },
                    },
                },
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
                        "className": "CUserPrincipalDetails",
                        "user": {
                            "id": "user-jdoe",
                            "username": "jdoe",
                            "name": {"firstName": "John", "lastName": "Doe"},
                        },
                    },
                },
                "time": 1705315200000,
            },
            {
                "id": "thread-msg-2",
                "text": "Done, added unit tests",
                "author": {
                    "name": "Anna.Zhukova",
                    "details": {
                        "className": "CUserPrincipalDetails",
                        "user": {
                            "id": "user-azhukova",
                            "username": "azhukova",
                            "name": {"firstName": "Anna", "lastName": "Zhukova"},
                        },
                    },
                },
                "time": 1705318800000,
            },
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
                    "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                    "createdAt": 1736937000000,
                    "branchPairs": [
                        {"sourceBranch": "azhukova/fix-auth", "targetBranch": "main", "repository": {"name": "ultimate"}}
                    ],
                }
            },
            {
                "review": {
                    "id": "123457",
                    "title": "Update dependencies",
                    "state": "Opened",
                    "createdBy": {"id": "user-jdoe", "name": "John Doe", "username": "jdoe"},
                    "createdAt": 1736850600000,
                    "branchPairs": [
                        {"sourceBranch": "jdoe/update-deps", "targetBranch": "main", "repository": {"name": "ultimate"}}
                    ],
                }
            },
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
                        "className": "CUserPrincipalDetails",
                        "user": {
                            "id": "user-jdoe",
                            "username": "jdoe",
                            "name": {"firstName": "John", "lastName": "Doe"},
                        },
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
                            "id": "user-azhukova",
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


# Patronus fixtures =====


@pytest.fixture
def patronus_client(space_client):
    """Create a PatronusClient instance with test token and SpaceClient."""
    return PatronusClient(token="test-token", space_client=space_client)


@pytest.fixture
def sample_run_overview():
    """Sample Patronus run overview response."""
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
            "id": "user-azhukova",
            "name": "Anna Zhukova",
            "email": "anna.zhukova@jetbrains.com",
        },
        "options": {},
        "spaceReviewKey": "IJ-MR-188120",
        "spaceReviewUrl": "https://jetbrains.team/p/IJ/reviews/188120/timeline",
    }


@pytest.fixture
def sample_runs_list(sample_run_overview):
    """Sample Patronus runs list response."""
    return {
        "me": {
            "type": "USER",
            "id": "user-azhukova",
            "name": "Anna Zhukova",
            "email": "anna.zhukova@jetbrains.com",
        },
        "robots": [sample_run_overview],
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
                "id": "check-1",
                "name": "Compile All",
                "status": "SUCCESS",
                "buildConfigurationId": "compile_all_id",
                "buildConfigurationName": "Compile All Build",
                "buildConfigurationProjectName": "Project / Build",
                "buildConfigurationUrl": "https://buildserver.labs.intellij.net/buildConfiguration/compile",
                "queuedAt": "2026-01-15T08:00:02Z",
                "startedAt": "2026-01-15T08:00:06Z",
                "finishedAt": "2026-01-15T08:05:00Z",
                "skipReason": None,
                "attemptLimit": 3,
                "attempts": [
                    {
                        "id": "attempt-1",
                        "number": 0,
                        "status": "SUCCESS",
                        "buildId": "98765",
                        "buildUrl": "https://buildserver.labs.intellij.net/build/98765",
                        "startedAt": "2026-01-15T08:00:06Z",
                        "finishedAt": "2026-01-15T08:05:00Z",
                        "failedTestsNumber": 0,
                        "failedBuildsNumber": 0,
                    }
                ],
            },
            {
                "id": "check-2",
                "name": "Unit Tests",
                "status": "FAILURE",
                "buildConfigurationId": "test_Build",
                "buildConfigurationName": "Unit Tests Build",
                "buildConfigurationProjectName": "Project / Tests",
                "buildConfigurationUrl": "https://buildserver.labs.intellij.net/buildConfiguration/test_Build",
                "queuedAt": "2026-01-15T08:00:02Z",
                "startedAt": "2026-01-15T08:00:06Z",
                "finishedAt": "2026-01-15T08:07:28Z",
                "skipReason": None,
                "attemptLimit": 3,
                "attempts": [
                    {
                        "id": "attempt-fail-1",
                        "number": 0,
                        "status": "FAILURE",
                        "buildId": "98770",
                        "buildUrl": "https://buildserver.labs.intellij.net/build/98770",
                        "startedAt": "2026-01-15T08:00:06Z",
                        "finishedAt": "2026-01-15T08:07:28Z",
                        "failedTestsNumber": 1,
                        "failedBuildsNumber": 1,
                    }
                ],
            },
        ],
    }


@pytest.fixture
def sample_teamcity_checks(sample_teamcity_checks_response):
    """The extracted list of TeamCity checks (what PatronusClient.get_run_teamcity_checks returns)."""
    return sample_teamcity_checks_response["teamCityChecks"]


@pytest.fixture
def sample_run_problems():
    """Sample Patronus run problems response."""
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


@pytest.fixture
def sample_created_merge_request():
    """Sample create merge request response from Space API."""
    return {
        "id": "abc123",
        "number": 194200,
        "title": "New feature",
        "state": "Opened",
        "createdAt": 1736937000000,
        "branchPairs": [
            {
                "sourceBranch": "azhukova/new-feature",
                "targetBranch": "master",
                "repository": {"name": "ultimate"},
            }
        ],
    }


@pytest.fixture
def sample_feed_messages_with_attachments():
    """Sample feed messages with file/image attachments and unfurls (to test filtering)."""
    return {
        "messages": [
            {
                "id": "feed-msg-att-1",
                "text": "Here is the screenshot and report",
                "author": {
                    "name": "Anna.Zhukova",
                    "details": {
                        "className": "CUserPrincipalDetails",
                        "user": {
                            "id": "user-azhukova",
                            "username": "azhukova",
                            "name": {"firstName": "Anna", "lastName": "Zhukova"},
                        },
                    },
                },
                "time": 1705320000000,
                "details": {"className": "MCMessage"},
                "attachments": [
                    {
                        "id": "att-1",
                        "details": {
                            "className": "ImageAttachment",
                            "id": "img-001",
                            "name": "screenshot.png",
                            "width": 1920,
                            "height": 1080,
                        },
                    },
                    {
                        "id": "att-2",
                        "details": {
                            "className": "FileAttachment",
                            "id": "file-001",
                            "filename": "report.txt",
                            "sizeBytes": 4096,
                        },
                    },
                ],
            },
            {
                "id": "feed-msg-att-2",
                "text": "Link preview here",
                "author": {
                    "name": "Bot",
                    "details": {
                        "className": "CApplicationPrincipalDetails",
                    },
                },
                "time": 1705320100000,
                "details": {"className": "MCMessage"},
                "attachments": [
                    {
                        "id": "att-3",
                        "details": {
                            "className": "UnfurlAttachment",
                            "id": "unfurl-001",
                        },
                    },
                ],
            },
        ]
    }


@pytest.fixture
def sample_discussion_thread_with_attachments():
    """Sample discussion thread messages with a file attachment."""
    return {
        "messages": [
            {
                "id": "thread-msg-att-1",
                "text": "Please review this log",
                "author": {
                    "name": "Anna.Zhukova",
                    "details": {
                        "className": "CUserPrincipalDetails",
                        "user": {
                            "id": "user-azhukova",
                            "username": "azhukova",
                            "name": {"firstName": "Anna", "lastName": "Zhukova"},
                        },
                    },
                },
                "time": 1705315200000,
                "attachments": [
                    {
                        "id": "att-4",
                        "details": {
                            "className": "FileAttachment",
                            "id": "file-002",
                            "filename": "build.log",
                            "sizeBytes": 102400,
                        },
                    },
                ],
            },
            {
                "id": "thread-msg-att-2",
                "text": "Looks good",
                "author": {
                    "name": "John.Doe",
                    "details": {
                        "className": "CUserPrincipalDetails",
                        "user": {
                            "id": "user-jdoe",
                            "username": "jdoe",
                            "name": {"firstName": "John", "lastName": "Doe"},
                        },
                    },
                },
                "time": 1705318800000,
            },
        ]
    }


# Fixtures for integration tests (real API calls, loaded from .env) =====


@pytest.fixture
def space_token():
    """Get SPACE_TOKEN from environment (loaded from .env by pytest-dotenv).

    Fails (not skips) if missing — a missing token is a CI configuration problem.
    """
    token = os.environ.get("SPACE_TOKEN")
    if not token:
        pytest.fail("SPACE_TOKEN not set — required for integration tests")
    return token


@pytest.fixture
def real_client(space_token):
    """Create a SpaceClient with real token for integration tests."""
    return SpaceClient(token=space_token)


@pytest.fixture
def real_patronus_client(space_token, real_client):
    """Create a PatronusClient with real token for integration tests."""
    base_url = os.environ.get("PATRONUS_URL", "https://patronus.labs.jb.gg")
    return PatronusClient(token=space_token, base_url=base_url, space_client=real_client)
