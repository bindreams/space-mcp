"""Tests for MCP markdown formatting functions."""

from space.mcp.format import (
    format_merge_request,
    format_create_result,
    format_find_result,
    format_discussions,
    format_merge_request_list,
    format_patronus_robots,
    format_patronus_robot_details,
    _human_size,
)


class TestFormatMergeRequest:

    def test_basic_structure(self, sample_merge_request):
        result = format_merge_request(sample_merge_request)
        assert "# [MR 188120] Fix authentication bug" in result
        assert "**State:** Opened" in result
        assert "`azhukova/fix-auth` -> `main`" in result

    def test_reviewer_table(self, sample_merge_request):
        result = format_merge_request(sample_merge_request)
        assert "| Reviewer | State |" in result
        assert "John Doe" in result
        assert "Pending" in result

    def test_no_description(self, sample_merge_request):
        """No description section when description is None."""
        result = format_merge_request(sample_merge_request)
        lines = result.split("\n")
        # Line after title should be empty, then State line
        assert lines[1] == ""
        assert lines[2].startswith("**State:**")

    def test_with_description(self, sample_merge_request):
        sample_merge_request["description"] = "This fixes the auth flow."
        result = format_merge_request(sample_merge_request)
        assert "This fixes the auth flow." in result
        # Description should be between title and state
        lines = result.split("\n")
        title_idx = next(i for i, l in enumerate(lines) if l.startswith("# [MR"))
        desc_idx = next(i for i, l in enumerate(lines) if "auth flow" in l)
        state_idx = next(i for i, l in enumerate(lines) if l.startswith("**State:**"))
        assert title_idx < desc_idx < state_idx

    def test_nested_name_format(self):
        """Handle Space API's nested name format (firstName/lastName)."""
        data = {
            "number": 1, "title": "Test", "description": None, "state": "Opened",
            "createdBy": {"name": {"firstName": "Anna", "lastName": "Zhukova"}, "username": "azhukova"},
            "branchPairs": [], "participants": [],
        }
        result = format_merge_request(data)
        assert "Anna Zhukova" in result


class TestFormatCreateResult:

    def test_basic_structure(self, sample_created_merge_request):
        result = format_create_result(sample_created_merge_request)
        assert "Merge request created." in result
        assert "**#194200** New feature" in result
        assert "`azhukova/new-feature` -> `master` (ultimate)" in result

    def test_no_branch_pairs(self):
        data = {"number": 1, "title": "Test", "branchPairs": []}
        result = format_create_result(data)
        assert "**#1** Test" in result


class TestFormatFindResult:

    def test_found(self, sample_merge_request):
        result = format_find_result(sample_merge_request)
        assert "# [MR 188120]" in result

    def test_not_found(self):
        result = format_find_result(None)
        assert result == "No merge request found."


class TestFormatDiscussions:

    def test_empty(self):
        assert format_discussions([]) == "No timeline items."

    def test_message_with_day_header(self):
        items = [{
            "type": "message", "text": "created the merge request",
            "author": {"username": "azhukova", "name": "Anna Zhukova"},
            "created": 1768512553167,
        }]
        result = format_discussions(items)
        # Day header should be present (exact date depends on system timezone)
        assert "## " in result
        assert "2026" in result
        assert "**Anna Zhukova**" in result
        assert "created the merge request" in result

    def test_day_sections(self):
        items = [
            {"type": "message", "text": "msg1", "author": {"name": "A"}, "created": 1768512553167},
            {"type": "message", "text": "msg2", "author": {"name": "A"}, "created": 1768598953167},
        ]
        result = format_discussions(items)
        # Should have two day headers
        assert result.count("## ") == 2

    def test_code_discussion(self):
        items = [{
            "type": "code_discussion",
            "file": "/src/auth.py", "line": 42, "resolved": True,
            "comments": [
                {"text": "Fix this", "author": {"name": "John"}, "created": 1768512553167},
                {"text": "Done", "author": {"name": "Anna"}, "created": 1768512600000},
            ],
        }]
        result = format_discussions(items)
        assert "`/src/auth.py:42`" in result
        assert "Fix this" in result
        assert "Done" in result

    def test_resolved_discussion_formatting(self):
        items = [{
            "type": "code_discussion",
            "file": "/src/foo.py", "line": 10, "resolved": True,
            "comments": [
                {"text": "Question", "author": {"name": "John"}, "created": 1768512553167},
                {"text": "User resolved the discussion", "author": {"name": "Anna"}, "created": 1768512600000},
            ],
        }]
        result = format_discussions(items)
        assert "*resolved the discussion*" in result

    def test_message_with_thread_replies(self):
        items = [{
            "type": "message", "text": "started a dry run",
            "author": {"name": "Anna Zhukova"},
            "created": 1768512553167,
            "thread_replies": [
                {"text": "Dry Run started", "author": {"name": "Patronus"}, "created": 1768512600000},
                {"text": "Dry Run **success**", "author": {"name": "Patronus"}, "created": 1768512700000},
            ],
        }]
        result = format_discussions(items)
        assert "started a dry run" in result
        assert "  - **Patronus**: Dry Run started" in result
        assert "  - **Patronus**: Dry Run **success**" in result


class TestFormatMergeRequestList:

    def test_empty(self):
        assert format_merge_request_list([]) == "No merge requests found."

    def test_table_structure(self):
        items = [{
            "title": "Fix bug", "state": "Opened",
            "createdBy": {"name": "Anna", "username": "a"},
            "branchPairs": [{"sourceBranch": "fix", "targetBranch": "main"}],
        }]
        result = format_merge_request_list(items)
        assert "| Title | State | Author | Branch |" in result
        assert "Fix bug" in result
        assert "`fix` -> `main`" in result


class TestFormatPatronusRobots:

    def test_empty(self):
        assert format_patronus_robots([]) == "No Patronus robots found."

    def test_table_with_robot_ids(self, sample_robot_overview):
        result = format_patronus_robots([sample_robot_overview])
        assert "| Status |" in result
        assert "SUCCESSFUL" in result
        assert "DRY_RUN" in result
        assert "Robot IDs" in result
        assert "cc448634-880e-411f-9ee6-347e9a6087ac" in result


class TestFormatPatronusRobotDetails:

    def test_basic_structure(self, sample_robot_overview, sample_teamcity_checks, sample_robot_problems):
        result = format_patronus_robot_details(sample_robot_overview, sample_teamcity_checks, sample_robot_problems)
        assert "# Fix auth (dry run)" in result
        assert "**Status:** SUCCESSFUL" in result
        assert "**Mode:** DRY_RUN" in result
        assert "patronus.labs.jb.gg" in result

    def test_tc_checks_table(self, sample_robot_overview, sample_teamcity_checks, sample_robot_problems):
        result = format_patronus_robot_details(sample_robot_overview, sample_teamcity_checks, sample_robot_problems)
        assert "## TeamCity Checks" in result
        assert "Compile All" in result
        assert "Unit Tests" in result

    def test_problems_section(self, sample_robot_overview, sample_teamcity_checks, sample_robot_problems):
        result = format_patronus_robot_details(sample_robot_overview, sample_teamcity_checks, sample_robot_problems)
        assert "## Problems" in result
        assert "3 tests failed in Unit Tests" in result
        assert "Failures in `com.example.FooTest`" in result

    def test_problems_without_details(self, sample_robot_overview, sample_teamcity_checks):
        problems = {"problems": [{"title": "Config not found", "detailsMarkdown": None}]}
        result = format_patronus_robot_details(sample_robot_overview, sample_teamcity_checks, problems)
        assert "**Config not found**" in result

    def test_no_problems(self, sample_robot_overview, sample_teamcity_checks):
        result = format_patronus_robot_details(sample_robot_overview, sample_teamcity_checks, {"problems": []})
        assert "None" in result

    def test_empty_tc_checks(self, sample_robot_overview, sample_robot_problems):
        result = format_patronus_robot_details(sample_robot_overview, [], sample_robot_problems)
        assert "No checks." in result

    def test_failed_checks_section(self, sample_robot_overview, sample_teamcity_checks, sample_robot_problems, sample_attempt_details):
        attempt_details = {"Unit Tests": sample_attempt_details}
        result = format_patronus_robot_details(
            sample_robot_overview, sample_teamcity_checks, sample_robot_problems, attempt_details
        )
        assert "## Failed Checks" in result
        assert "### Unit Tests" in result
        assert "com.example.FooTest.test something important" in result
        assert "Process exited with code 1 (Step: test)" in result
        assert "1 failed test detected" in result

    def test_no_attempt_details(self, sample_robot_overview, sample_teamcity_checks, sample_robot_problems):
        """No Failed Checks section when attempt_details is empty."""
        result = format_patronus_robot_details(
            sample_robot_overview, sample_teamcity_checks, sample_robot_problems, {}
        )
        assert "## Failed Checks" not in result


class TestHumanSize:

    def test_bytes(self):
        assert _human_size(500) == "500 B"

    def test_kilobytes(self):
        assert _human_size(4096) == "4.0 KB"

    def test_megabytes(self):
        assert _human_size(1048576) == "1.0 MB"

    def test_gigabytes(self):
        assert _human_size(1073741824) == "1.0 GB"

    def test_none(self):
        assert _human_size(None) == ""

    def test_zero(self):
        assert _human_size(0) == "0 B"


class TestFormatDiscussionsWithAttachments:

    def test_message_with_attachments(self):
        items = [{
            "type": "message",
            "text": "Here is the file",
            "author": {"name": "Anna"},
            "created": 1768512553167,
            "attachments": [{
                "id": "file-001",
                "type": "file",
                "name": "report.txt",
                "size_bytes": 4096,
                "width": None,
                "height": None,
                "download_url": "https://jetbrains.team/d/file-001",
            }],
        }]
        result = format_discussions(items)
        assert "report.txt" in result
        assert "4.0 KB" in result
        assert "file-001" in result

    def test_attachment_shows_name_size_id(self):
        items = [{
            "type": "message",
            "text": "Screenshot",
            "author": {"name": "Anna"},
            "created": 1768512553167,
            "attachments": [{
                "id": "img-001",
                "type": "image",
                "name": "screenshot.png",
                "size_bytes": None,
                "width": 1920,
                "height": 1080,
                "download_url": "https://jetbrains.team/d/img-001",
            }],
        }]
        result = format_discussions(items)
        assert "`screenshot.png`" in result
        assert "img-001" in result

    def test_thread_reply_with_attachments(self):
        items = [{
            "type": "message",
            "text": "started a dry run",
            "author": {"name": "Anna"},
            "created": 1768512553167,
            "thread_replies": [{
                "text": "Here are the results",
                "author": {"name": "Patronus"},
                "created": 1768512600000,
                "attachments": [{
                    "id": "f1",
                    "type": "file",
                    "name": "results.txt",
                    "size_bytes": 2048,
                    "width": None,
                    "height": None,
                    "download_url": "https://jetbrains.team/d/f1",
                }],
            }],
        }]
        result = format_discussions(items)
        assert "results.txt" in result
        # Reply attachments should be further indented than message ones
        lines = result.split("\n")
        att_lines = [l for l in lines if "results.txt" in l]
        assert len(att_lines) == 1
        assert att_lines[0].startswith("    ")

    def test_code_discussion_comment_with_attachments(self):
        items = [{
            "type": "code_discussion",
            "file": "/src/auth.py",
            "line": 42,
            "resolved": False,
            "comments": [
                {
                    "text": "See attached log",
                    "author": {"name": "Anna"},
                    "created": 1768512553167,
                    "attachments": [{
                        "id": "f2",
                        "type": "file",
                        "name": "error.log",
                        "size_bytes": 8192,
                        "width": None,
                        "height": None,
                        "download_url": "https://jetbrains.team/d/f2",
                    }],
                },
            ],
        }]
        result = format_discussions(items)
        assert "error.log" in result
        assert "8.0 KB" in result
