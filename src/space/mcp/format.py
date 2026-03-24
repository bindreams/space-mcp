"""Markdown formatting for MCP tool responses."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from ..models.status import FAILING, effective_status

if TYPE_CHECKING:
    from ..models import (
        Attachment,
        AttemptDetails,
        CodeDiscussion,
        Comment,
        MergeRequest,
        PatronusCheckRun,
        PatronusRun,
        Problem,
        SpacePrincipal,
        TimelineItem,
        TimelineMessage,
    )


def _time(dt: datetime | None) -> str:
    """Format datetime as HH:MM in local timezone."""
    if dt is None:
        return ""
    return dt.astimezone().strftime("%H:%M")


def _date_header(dt: datetime | None) -> str:
    """Format datetime as 'January 16, 2026'."""
    if dt is None:
        return ""
    return dt.astimezone().strftime("%B %d, %Y").replace(" 0", " ")


def _short_date(dt: datetime | None) -> str:
    """Format datetime as 'Jan 16' (for cross-day thread replies)."""
    if dt is None:
        return ""
    return dt.astimezone().strftime("%b %d").replace(" 0", " ")


def _human_size(n: int | None) -> str:
    """Format byte count as human-readable size (e.g. '4.0 KB')."""
    if n is None:
        return ""
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024
        if n < 1024:
            return f"{n:.1f} {unit}"
    return f"{n:.1f} TB"


def _format_attachments(
    attachments: tuple[Attachment, ...], indent: str = "  ",
) -> str:
    """Format attachment list as a single indented line."""
    parts = []
    for att in attachments:
        size_str = f" ({_human_size(att.size_bytes)})" if att.size_bytes else ""
        parts.append(f"`{att.name}`{size_str} [id: {att.id}]")
    return f"{indent}Attachments: " + ", ".join(parts)


def _author(principal: SpacePrincipal | None) -> str:
    """Format author as **Name**."""
    if principal is None:
        return "**Unknown**"
    return f"**{principal.name}**"


# MR details =====


def format_merge_request(mr: MergeRequest) -> str:
    """Format a merge request as markdown."""
    lines = [f"# [MR {mr.number}] {mr.title}"]

    if mr.description:
        lines.append("")
        lines.append(mr.description)

    author = mr.created_by.name if mr.created_by else "Unknown"
    lines.append("")
    lines.append(f"**State:** {mr.state.value} | **Author:** {author}")

    for bp in mr.branch_pairs:
        lines.append(f"**Branch:** `{bp.source_branch}` -> `{bp.target_branch}` ({bp.repository})")

    # Participants table -----
    from ..models import ReviewRole
    reviewers = [p for p in mr.participants if p.role != ReviewRole.AUTHOR]
    if reviewers:
        lines.append("")
        lines.append("| Reviewer | State |")
        lines.append("|----------|-------|")
        for p in reviewers:
            state_val = p.state.value if p.state else "-"
            lines.append(f"| {p.user.name} | {state_val} |")

    return "\n".join(lines)


def format_create_result(mr: MergeRequest) -> str:
    """Format create_merge_request result as markdown."""
    lines = ["Merge request created.", "", f"**#{mr.number}** {mr.title}"]

    for bp in mr.branch_pairs:
        lines.append(f"`{bp.source_branch}` -> `{bp.target_branch}` ({bp.repository})")

    return "\n".join(lines)


# Timeline / discussions =====


def format_discussions(items: list[TimelineItem]) -> str:
    """Format timeline items as chronological markdown with day sections and threads."""
    from ..models import CodeDiscussion as CD, TimelineMessage as TM

    if not items:
        return "No timeline items."

    lines: list[str] = []
    current_day = ""

    for item in items:
        if isinstance(item, CD):
            first_ts = item.comments[0].created_at if item.comments else None
            day = _date_header(first_ts)
            if day and day != current_day:
                current_day = day
                lines.append(f"\n## {day}\n")

            file_path = item.file or "?"
            line_num = item.line if item.line is not None else "?"
            resolved = " [resolved]" if item.resolved else ""
            if item.comments:
                first = item.comments[0]
                resolved_suffix = resolved if len(item.comments) == 1 else ""
                lines.append(
                    f"- {_author(first.author)} "
                    f"({_time(first.created_at)}) "
                    f"commented on `{file_path}:{line_num}`: "
                    f"{first.text}{resolved_suffix}"
                )
                if first.attachments:
                    lines.append(_format_attachments(first.attachments, "  "))
                for reply in item.comments[1:]:
                    if reply.text.startswith("User resolved the discussion"):
                        lines.append(f"  - {_author(reply.author)}: *resolved the discussion*")
                    elif reply.text.startswith("User reopened the discussion"):
                        lines.append(f"  - {_author(reply.author)}: *reopened the discussion*")
                    else:
                        lines.append(f"  - {_author(reply.author)}: {reply.text}")
                    if reply.attachments:
                        lines.append(_format_attachments(reply.attachments, "    "))
            else:
                lines.append(f"- Comment on `{file_path}:{line_num}`{resolved}")

        elif isinstance(item, TM):
            day = _date_header(item.created_at)
            if day and day != current_day:
                current_day = day
                lines.append(f"\n## {day}\n")

            lines.append(f"- {_author(item.author)} ({_time(item.created_at)}): {item.text}")
            if item.attachments:
                lines.append(_format_attachments(item.attachments))

            for reply in item.thread_replies:
                lines.append(f"  - {_author(reply.author)}: {reply.text}")
                if reply.attachments:
                    lines.append(_format_attachments(reply.attachments, "    "))

    return "\n".join(lines)


# MR list =====


def format_merge_request_list(items: list[MergeRequest]) -> str:
    """Format a list of merge requests as a markdown table."""
    if not items:
        return "No merge requests found."

    lines = ["| Title | State | Author | Branch |", "|-------|-------|--------|--------|"]
    for mr in items:
        author = mr.created_by.name if mr.created_by else "Unknown"
        branches = ""
        if mr.branch_pairs:
            bp = mr.branch_pairs[0]
            branches = f"`{bp.source_branch}` -> `{bp.target_branch}`"
        lines.append(f"| {mr.title} | {mr.state.value} | {author} | {branches} |")

    return "\n".join(lines)


# Patronus =====


def format_patronus_runs(
    items: list[PatronusRun],
    commits: dict[str, str | None],
    checks: dict[str, Sequence[PatronusCheckRun]] | None = None,
) -> str:
    """Format a list of Patronus runs as markdown."""
    if not items:
        return "No Patronus runs found."

    # Sort newest-to-oldest by finished_at (falling back to started_at)
    sorted_items = sorted(
        items,
        key=lambda r: r.finished_at or r.started_at,
        reverse=True,
    )

    lines = [
        "| Run ID | Status | Mode | Commit | Finished |",
        "|--------|--------|------|--------|----------|",
    ]
    for r in sorted_items:
        run_id_short = r.id[:8]
        commit = commits.get(r.id)
        commit_display = f"`{commit}`" if commit else "?"
        display_status = effective_status(r, (checks or {}).get(r.id))
        if r.finished_at:
            finished = r.finished_at.astimezone().strftime("%b %d, %H:%M")
        elif display_status in ("RUNNING", FAILING):
            finished = "*(still running)*"
        else:
            finished = "*(still queued)*"
        lines.append(
            f"| `{run_id_short}` | {display_status} | {r.push_mode.value} "
            f"| {commit_display} | {finished} |"
        )

    return "\n".join(lines)


def format_patronus_run_details(
    run: PatronusRun,
    tc_checks: list[PatronusCheckRun],
    problems: tuple[Problem, ...],
    attempt_details: dict[str, AttemptDetails] | None = None,
) -> str:
    """Format Patronus run details as markdown."""
    display_status = effective_status(run, tc_checks)
    lines = [f"# {run.name}"]

    lines.append("")
    lines.append(f"**Status:** {display_status} | **Mode:** {run.push_mode.value}")
    lines.append(f"**Owner:** {run.owner.name}")
    lines.append(f"**Branch:** `{run.branch_pair.source_branch}` -> `{run.branch_pair.target_branch}` ({run.branch_pair.repository})")

    if run.started_at:
        lines.append(f"**Started:** {run.started_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}")
    if run.finished_at:
        lines.append(f"**Finished:** {run.finished_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}")

    lines.append(f"**Patronus:** https://patronus.labs.jb.gg/robot/{run.id}")

    if run.space_review_url:
        lines.append(f"**Space MR:** {run.space_review_url}")

    # TC checks -----
    if tc_checks:
        by_status: dict[str, int] = {}
        for check in tc_checks:
            s = check.status.value
            by_status[s] = by_status.get(s, 0) + 1
        summary = ", ".join(f"{count} {status.lower()}" for status, count in sorted(by_status.items()))
        lines.append(f"\n## TeamCity Checks ({len(tc_checks)} total: {summary})\n")
        lines.append("| Status | Name | Build Config |")
        lines.append("|--------|------|-------------|")
        for check in tc_checks:
            c_url = check.config.build_configuration_url
            if c_url:
                lines.append(f"| {check.status.value} | {check.config.name} | [link]({c_url}) |")
            else:
                lines.append(f"| {check.status.value} | {check.config.name} | - |")
    else:
        lines.append("\n## TeamCity Checks\n")
        lines.append("No checks.")

    # Failed checks details -----
    if attempt_details:
        lines.append("\n## Failed Checks\n")
        for check_name, details in attempt_details.items():
            lines.append(f"### {check_name}\n")
            if details.failed_tests:
                lines.append(f"Failed tests ({len(details.failed_tests)}):")
                for test in details.failed_tests:
                    lines.append(f"- {test.name}")
            if details.failed_builds:
                for build in details.failed_builds:
                    if build.problems:
                        if build.build_configuration_name:
                            lines.append(f"\nBuild problems ({build.build_configuration_name}):")
                        else:
                            lines.append("\nBuild problems:")
                        for bp in build.problems:
                            lines.append(f"- {bp}")
            lines.append("")

    # Problems -----
    lines.append("\n## Problems\n")
    if problems:
        for p in problems:
            lines.append(f"- **{p.title}**")
            if p.details:
                for detail_line in p.details.splitlines():
                    lines.append(f"  {detail_line}")
    else:
        lines.append("None")

    return "\n".join(lines)
