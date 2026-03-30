"""YAML and Markdown formatting for MCP tool responses."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from ..formatting import human_size as _human_size
from ..models.patronus import iso_local
from ..models.status import effective_status
from .yaml_utils import dump_yaml

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


def _format_attachments(
    attachments: tuple[Attachment, ...],
    indent: str = "  ",
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


# MR details ===========================================================================================================


def format_merge_request(mr: MergeRequest) -> str:
    """Format a merge request as YAML."""
    return dump_yaml({"merge-request": mr.dump()})


def format_create_result(mr: MergeRequest) -> str:
    """Format create_merge_request result as YAML."""
    d = mr.dump()
    for key in ("state", "author", "reviewers", "description"):
        d.pop(key, None)
    return dump_yaml({"create-success": True, "merge-request": d})


# Timeline / discussions ===============================================================================================


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
            channel_tag = f" (channel: `{item.channel_id}`)" if item.channel_id else ""
            if item.comments:
                first = item.comments[0]
                resolved_suffix = resolved if len(item.comments) == 1 else ""
                lines.append(
                    f"- {_author(first.author)} "
                    f"({_time(first.created_at)}) "
                    f"commented on `{file_path}:{line_num}`{channel_tag}: "
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
                lines.append(f"- Comment on `{file_path}:{line_num}`{resolved}{channel_tag}")

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


# MR list ==============================================================================================================


def format_merge_request_list(items: list[MergeRequest]) -> str:
    """Format a list of merge requests as YAML."""
    if not items:
        return "No merge requests found."
    return dump_yaml({"merge-requests": [mr.dump() for mr in items]})


# Patronus =============================================================================================================


def format_patronus_runs(
    items: list[PatronusRun],
    commits: dict[str, str | None],
    checks: dict[str, Sequence[PatronusCheckRun]] | None = None,
) -> str:
    """Format a list of Patronus runs as YAML."""
    if not items:
        return "No Patronus runs found."

    _epoch = datetime.min.replace(tzinfo=timezone.utc)
    sorted_items = sorted(
        items,
        key=lambda r: r.finished_at or r.started_at or _epoch,
        reverse=True,
    )

    runs = []
    for r in sorted_items:
        commit = commits.get(r.id)
        d: dict[str, Any] = {
            "run-id": r.id,
            "status": effective_status(r, (checks or {}).get(r.id)),
            "mode": r.push_mode.value,
            "commit": commit if commit else None,
            "finished-at": iso_local(r.finished_at),
        }
        runs.append(d)
    return dump_yaml({"patronus-runs": runs})


def format_patronus_run_details(
    run: PatronusRun,
    tc_checks: list[PatronusCheckRun],
    problems: tuple[Problem, ...],
    attempt_details: dict[str, AttemptDetails] | None = None,
    patronus_base_url: str = "https://patronus.labs.jb.gg",
) -> str:
    """Format Patronus run details as YAML."""
    d = run.dump(patronus_base_url=patronus_base_url)
    d["status"] = effective_status(run, tc_checks)

    if tc_checks:
        details = attempt_details or {}
        by_status: dict[str, int] = {}
        for check in tc_checks:
            s = check.status.value
            by_status[s] = by_status.get(s, 0) + 1
        summary = ", ".join(f"{count} {status.lower()}" for status, count in sorted(by_status.items()))
        d["teamcity-checks"] = {
            "summary": f"{len(tc_checks)} total, {summary}",
            "checks": [check.dump(attempt=details.get(check.config.name)) for check in tc_checks],
        }
    else:
        d["teamcity-checks"] = "no checks configured"

    d["problems"] = [p.dump() for p in problems]

    return dump_yaml({"patronus-run": d})
