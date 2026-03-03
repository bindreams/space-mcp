"""Markdown formatting for MCP tool responses."""

from datetime import datetime, timezone
from typing import Any


def _ts(epoch_ms: int | None) -> datetime | None:
    """Convert epoch milliseconds to datetime in system timezone."""
    if epoch_ms is None:
        return None
    return datetime.fromtimestamp(epoch_ms / 1000).astimezone()


def _time(epoch_ms: int | None) -> str:
    """Format epoch ms as HH:MM."""
    dt = _ts(epoch_ms)
    return dt.strftime("%H:%M") if dt else ""


def _date_header(epoch_ms: int | None) -> str:
    """Format epoch ms as 'January 16, 2026'."""
    dt = _ts(epoch_ms)
    return dt.strftime("%B %d, %Y").replace(" 0", " ") if dt else ""


def _short_date(epoch_ms: int | None) -> str:
    """Format epoch ms as 'Jan 16' (for cross-day thread replies)."""
    dt = _ts(epoch_ms)
    return dt.strftime("%b %d").replace(" 0", " ") if dt else ""


def _author(author: dict[str, Any] | None) -> str:
    """Format author as **Name**."""
    if not author:
        return "**Unknown**"
    name = author.get("name") or author.get("username") or "Unknown"
    return f"**{name}**"


def _extract_name(created_by: dict[str, Any]) -> str:
    """Extract display name from createdBy field (handles both flat and nested formats)."""
    name = created_by.get("name")
    if isinstance(name, dict):
        first = name.get("firstName", "")
        last = name.get("lastName", "")
        return f"{first} {last}".strip() or created_by.get("username", "Unknown")
    return name or created_by.get("username", "Unknown")


# MR details =================================================================


def format_merge_request(data: dict[str, Any]) -> str:
    """Format a merge request as markdown."""
    number = data.get("number", "?")
    title = data.get("title", "Untitled")
    lines = [f"# [MR {number}] {title}"]

    description = data.get("description")
    if description:
        lines.append("")
        lines.append(description)

    state = data.get("state", "Unknown")
    author = _extract_name(data.get("createdBy", {}))
    lines.append("")
    lines.append(f"**State:** {state} | **Author:** {author}")

    for bp in data.get("branchPairs", []):
        repo = bp.get("repository")
        repo_name = repo.get("name") if isinstance(repo, dict) else repo
        lines.append(f"**Branch:** `{bp.get('sourceBranch')}` -> `{bp.get('targetBranch')}` ({repo_name})")

    # Participants table -----
    participants = data.get("participants", [])
    reviewers = [p for p in participants if p.get("role") != "Author"]
    if reviewers:
        lines.append("")
        lines.append("| Reviewer | State |")
        lines.append("|----------|-------|")
        for p in reviewers:
            user = p.get("user", {})
            name = _extract_name(user)
            state_val = p.get("state") or "-"
            lines.append(f"| {name} | {state_val} |")

    return "\n".join(lines)


def format_create_result(data: dict[str, Any]) -> str:
    """Format create_merge_request result as markdown."""
    number = data.get("number", "?")
    title = data.get("title", "Untitled")
    lines = [f"Merge request created.", "", f"**#{number}** {title}"]

    for bp in data.get("branchPairs", []):
        repo = bp.get("repository")
        repo_name = repo.get("name") if isinstance(repo, dict) else repo
        lines.append(f"`{bp.get('sourceBranch')}` -> `{bp.get('targetBranch')}` ({repo_name})")

    return "\n".join(lines)


def format_find_result(data: dict[str, Any] | None) -> str:
    """Format find_merge_request_by_branch result."""
    if data is None:
        return "No merge request found."
    return format_merge_request(data)


# Timeline / discussions ======================================================


def format_discussions(items: list[dict[str, Any]]) -> str:
    """Format timeline items as chronological markdown with day sections and threads."""
    if not items:
        return "No timeline items."

    lines: list[str] = []
    current_day = ""

    for item in items:
        item_type = item.get("type")

        if item_type == "code_discussion":
            # Code discussions don't have a top-level timestamp; use first comment's time
            first_ts = item.get("comments", [{}])[0].get("created") if item.get("comments") else None
            day = _date_header(first_ts)
            if day and day != current_day:
                current_day = day
                lines.append(f"\n## {day}\n")

            file_path = item.get("file", "?")
            line_num = item.get("line", "?")
            resolved = " [resolved]" if item.get("resolved") else ""
            comments = item.get("comments", [])
            if comments:
                first = comments[0]
                lines.append(f"- {_author(first.get('author'))} ({_time(first.get('created'))}) commented on `{file_path}:{line_num}`: {first.get('text', '')}{resolved if len(comments) == 1 else ''}")
                for reply in comments[1:]:
                    text = reply.get("text", "")
                    # Cosmetic-only: Space generates these exact strings for resolve/reopen actions.
                    # The actual resolved state is tracked by the parent's `resolved` boolean.
                    if text.startswith("User resolved the discussion"):
                        lines.append(f"  - {_author(reply.get('author'))}: *resolved the discussion*")
                    elif text.startswith("User reopened the discussion"):
                        lines.append(f"  - {_author(reply.get('author'))}: *reopened the discussion*")
                    else:
                        lines.append(f"  - {_author(reply.get('author'))}: {text}")
            else:
                lines.append(f"- Comment on `{file_path}:{line_num}`{resolved}")

        elif item_type == "message":
            created = item.get("created")
            day = _date_header(created)
            if day and day != current_day:
                current_day = day
                lines.append(f"\n## {day}\n")

            text = item.get("text", "")
            lines.append(f"- {_author(item.get('author'))} ({_time(created)}): {text}")

            # Thread replies (dry runs, safe merges, etc.)
            for reply in item.get("thread_replies", []):
                reply_text = reply.get("text", "")
                lines.append(f"  - {_author(reply.get('author'))}: {reply_text}")

    return "\n".join(lines)


# MR list =====================================================================


def format_merge_request_list(items: list[dict[str, Any]]) -> str:
    """Format a list of merge requests as a markdown table."""
    if not items:
        return "No merge requests found."

    lines = ["| Title | State | Author | Branch |", "|-------|-------|--------|--------|"]
    for mr in items:
        title = mr.get("title", "?")
        state = mr.get("state", "?")
        author = _extract_name(mr.get("createdBy", {}))
        branches = ""
        for bp in mr.get("branchPairs", []):
            branches = f"`{bp.get('sourceBranch')}` -> `{bp.get('targetBranch')}`"
            break
        lines.append(f"| {title} | {state} | {author} | {branches} |")

    return "\n".join(lines)


# Patronus ====================================================================


def format_patronus_robots(items: list[dict[str, Any]]) -> str:
    """Format a list of Patronus robots as markdown."""
    if not items:
        return "No Patronus robots found."

    lines = ["| Status | Name | Mode | Branch | Owner | Started |", "|--------|------|------|--------|-------|---------|"]
    robot_ids: list[str] = []
    for r in items:
        status = r.get("status", "?")
        name = r.get("name", "?")
        mode = r.get("pushMode", "?")
        source = r.get("sourceBranch", "?")
        target = r.get("targetBranch", "?")
        owner = r.get("owner", {}).get("name", "?")
        started = _short_date(None)  # startDateTime is ISO, not epoch
        start_dt = r.get("startDateTime")
        if start_dt:
            try:
                dt = datetime.fromisoformat(start_dt.replace("Z", "+00:00"))
                started = dt.strftime("%b %d, %H:%M")
            except (ValueError, TypeError):
                started = start_dt[:16]
        lines.append(f"| {status} | {name} | {mode} | `{source}` -> `{target}` | {owner} | {started} |")
        robot_ids.append(r.get("id", "?"))

    lines.append("")
    lines.append("Robot IDs for `get_patronus_robot_details`:")
    for rid in robot_ids:
        lines.append(f"- `{rid}`")

    return "\n".join(lines)


def format_patronus_robot_details(
    robot: dict[str, Any],
    tc_checks: list[dict[str, Any]],
    problems: dict[str, Any],
    attempt_details: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Format Patronus robot details as markdown."""
    name = robot.get("name", "?")
    lines = [f"# {name}"]

    status = robot.get("status", "?")
    mode = robot.get("pushMode", "?")
    owner = robot.get("owner", {}).get("name", "?")
    source = robot.get("sourceBranch", "?")
    target = robot.get("targetBranch", "?")
    repo = robot.get("repository", "?")
    robot_id = robot.get("id", "?")

    lines.append("")
    lines.append(f"**Status:** {status} | **Mode:** {mode}")
    lines.append(f"**Owner:** {owner}")
    lines.append(f"**Branch:** `{source}` -> `{target}` ({repo})")

    start_dt = robot.get("startDateTime", "")
    if start_dt:
        lines.append(f"**Started:** {start_dt[:19].replace('T', ' ')}")
    finish_dt = robot.get("finishDateTime")
    if finish_dt:
        lines.append(f"**Finished:** {finish_dt[:19].replace('T', ' ')}")

    lines.append(f"**Patronus:** https://patronus.labs.jb.gg/robot/{robot_id}")

    review_url = robot.get("spaceReviewUrl")
    if review_url:
        lines.append(f"**Space MR:** {review_url}")

    # TC checks -----
    if tc_checks:
        by_status: dict[str, int] = {}
        for check in tc_checks:
            s = check.get("status", "UNKNOWN")
            by_status[s] = by_status.get(s, 0) + 1
        summary = ", ".join(f"{count} {status.lower()}" for status, count in sorted(by_status.items()))
        lines.append(f"\n## TeamCity Checks ({len(tc_checks)} total: {summary})\n")
        lines.append("| Status | Name | Build Config |")
        lines.append("|--------|------|-------------|")
        for check in tc_checks:
            c_status = check.get("status", "?")
            c_name = check.get("name", "?")
            c_url = check.get("buildConfigurationUrl", "")
            if c_url:
                lines.append(f"| {c_status} | {c_name} | [link]({c_url}) |")
            else:
                lines.append(f"| {c_status} | {c_name} | - |")
    else:
        lines.append("\n## TeamCity Checks\n")
        lines.append("No checks.")

    # Failed checks details -----
    if attempt_details:
        lines.append("\n## Failed Checks\n")
        for check_name, details in attempt_details.items():
            lines.append(f"### {check_name}\n")
            failed_tests = details.get("failedTests", [])
            if failed_tests:
                lines.append(f"Failed tests ({len(failed_tests)}):")
                for test in failed_tests:
                    lines.append(f"- {test.get('name', '?')}")
            failed_builds = details.get("failedBuilds", [])
            if failed_builds:
                for build in failed_builds:
                    build_problems = build.get("problems", [])
                    if build_problems:
                        build_name = build.get("buildConfigurationName", "")
                        if build_name:
                            lines.append(f"\nBuild problems ({build_name}):")
                        else:
                            lines.append("\nBuild problems:")
                        for bp in build_problems:
                            lines.append(f"- {bp.get('details', '?')}")
            lines.append("")

    # Problems -----
    problem_list = problems.get("problems", []) if isinstance(problems, dict) else []
    lines.append("\n## Problems\n")
    if problem_list:
        for p in problem_list:
            lines.append(f"- **{p.get('title', '?')}**")
            if p.get("detailsMarkdown"):
                # Indent each line of the markdown details
                for detail_line in p["detailsMarkdown"].splitlines():
                    lines.append(f"  {detail_line}")
    else:
        lines.append("None")

    return "\n".join(lines)
