"""Module-level constants for sample API response dicts used by test fixtures."""

SAMPLE_MERGE_REQUEST = {
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
    "participants": [{
        "user": {"id": "user-jdoe", "name": "John Doe", "username": "jdoe"},
        "role": "Reviewer",
        "state": "Pending",
    }],
    "branchPair": {
        "sourceBranch": "azhukova/fix-auth",
        "targetBranch": "main",
        "repository": {"name": "ultimate"},
    },
    "feedChannel": {
        "id": "test-channel-id",
    },
}

SAMPLE_REVIEW_WITH_CHANNEL = {"feedChannel": {
    "id": "test-channel-id",
}}

SAMPLE_FEED_MESSAGES = {
    "messages": [{
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
    }]
}

SAMPLE_DISCUSSION_THREAD = {
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

SAMPLE_MERGE_REQUEST_LIST = {
    "data": [
        {
            "review": {
                "id": "123456",
                "title": "Fix authentication bug",
                "state": "Opened",
                "createdBy": {"id": "user-azhukova", "name": "Anna Zhukova", "username": "azhukova"},
                "createdAt": 1736937000000,
                "branchPair": {
                    "sourceBranch": "azhukova/fix-auth", "targetBranch": "main", "repository": {"name": "ultimate"}
                },
            }
        },
        {
            "review": {
                "id": "123457",
                "title": "Update dependencies",
                "state": "Opened",
                "createdBy": {"id": "user-jdoe", "name": "John Doe", "username": "jdoe"},
                "createdAt": 1736850600000,
                "branchPair": {
                    "sourceBranch": "jdoe/update-deps", "targetBranch": "main", "repository": {"name": "ultimate"}
                },
            }
        },
    ]
}

EMPTY_MERGE_REQUEST_LIST = {"data": []}

SAMPLE_FEED_MESSAGES_WITH_GENERAL = {
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

SAMPLE_RUN_OVERVIEW = {
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

SAMPLE_TEAMCITY_CHECKS_RESPONSE = {
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
            "attempts": [{
                "id": "attempt-1",
                "number": 0,
                "status": "SUCCESS",
                "buildId": "98765",
                "buildUrl": "https://buildserver.labs.intellij.net/build/98765",
                "startedAt": "2026-01-15T08:00:06Z",
                "finishedAt": "2026-01-15T08:05:00Z",
                "failedTestsNumber": 0,
                "failedBuildsNumber": 0,
            }],
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
            "attempts": [{
                "id": "attempt-fail-1",
                "number": 0,
                "status": "FAILURE",
                "buildId": "98770",
                "buildUrl": "https://buildserver.labs.intellij.net/build/98770",
                "startedAt": "2026-01-15T08:00:06Z",
                "finishedAt": "2026-01-15T08:07:28Z",
                "failedTestsNumber": 1,
                "failedBuildsNumber": 1,
            }],
        },
    ],
}

SAMPLE_RUN_PROBLEMS = {
    "robotId": "cc448634-880e-411f-9ee6-347e9a6087ac",
    "problems": [{
        "title": "3 tests failed in Unit Tests",
        "detailsMarkdown": "Failures in `com.example.FooTest`",
    }],
}

SAMPLE_ATTEMPT_DETAILS = {
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
    "failedTests": [{
        "name": "com.example.FooTest.test something important",
        "url": "https://buildserver.labs.intellij.net/test/123",
    }],
    "failedBuilds": [{
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
    }],
}

SAMPLE_CREATED_MERGE_REQUEST = {
    "id": "abc123",
    "number": 194200,
    "title": "New feature",
    "state": "Opened",
    "createdAt": 1736937000000,
    "branchPair": {
        "sourceBranch": "azhukova/new-feature",
        "targetBranch": "master",
        "repository": {"name": "ultimate"},
    },
}

SAMPLE_FEED_MESSAGES_WITH_ATTACHMENTS = {
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

SAMPLE_DISCUSSION_THREAD_WITH_ATTACHMENTS = {
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
