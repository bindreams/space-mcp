from __future__ import annotations

import functools
import re

import httpx
from mcp.server.fastmcp import FastMCP

from ..clients import get_client, get_patronus_client
from ..context import AuthenticationError
from ..models import RunStatus, TimelineMessage
from .format import (
    format_merge_request,
    format_create_result,
    format_find_result,
    format_discussions,
    format_merge_request_list,
    format_patronus_robots,
    format_patronus_robot_details,
    _human_size,
)

# Initialize MCP server
mcp = FastMCP("space")

_AUTH_ERROR_MSG = (
    "**Authentication required.** Set the `SPACE_TOKEN` environment variable "
    "or run `space auth login` to store credentials."
)


def _format_error(exc: Exception) -> str:
    """Format an exception into a user-friendly error message."""
    if isinstance(exc, AuthenticationError):
        return _AUTH_ERROR_MSG
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        detail = exc.response.text or exc.response.reason_phrase or str(exc) or f"HTTP {status}"
        return f"**Space API error ({status}):** {detail}"
    msg = str(exc) or type(exc).__name__
    return f"**Error:** {msg}"


def _handle_errors(func):
    """Decorator that catches exceptions and returns formatted error messages."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            return _format_error(exc)
    return wrapper


@mcp.tool()
@_handle_errors
async def get_merge_request(project: str, repository: str, review_id: str) -> str:
    """Get details of a specific merge request.

    Args:
        project: Project key (e.g., "ij" for IntelliJ)
        repository: Repository name (e.g., "ultimate")
        review_id: Review/MR identifier (numeric ID or full review ID)

    Returns:
        Markdown with MR title, state, author, branches, and reviewer table.
    """
    client = get_client()
    result = await client.get_merge_request(project, repository, review_id)
    return format_merge_request(result)


@mcp.tool()
@_handle_errors
async def get_merge_request_discussions(project: str, repository: str, review_id: str) -> str:
    """Get the full timeline of a merge request: comments, dry runs, commits, reviews.

    Returns a chronological markdown timeline with day sections, threaded replies
    (Patronus dry run results, safe merge status), and code review discussions.

    Args:
        project: Project key (e.g., "ij")
        repository: Repository name (e.g., "ultimate")
        review_id: Review/MR identifier

    Returns:
        Markdown timeline grouped by day, with threaded replies indented.
    """
    client = get_client()
    result = await client.get_merge_request_discussions(project, repository, review_id)
    return format_discussions(result)


@mcp.tool()
@_handle_errors
async def list_merge_requests(
    project: str,
    repository: str,
    branch: str | None = None,
    state: str | None = None,
    limit: int = 20,
) -> str:
    """List merge requests for a repository.

    Args:
        project: Project key (e.g., "ij")
        repository: Repository name (e.g., "ultimate")
        branch: Optional source branch name to filter by
        state: Optional state filter: "Open", "Closed", or "Merged"
        limit: Maximum number of results (default 20)

    Returns:
        Markdown table of merge requests.
    """
    client = get_client()
    result = await client.list_merge_requests(
        project=project,
        repository=repository,
        branch=branch,
        state=state,
        limit=limit,
    )
    return format_merge_request_list(result)


@mcp.tool()
@_handle_errors
async def find_merge_request_by_branch(
    project: str,
    repository: str,
    branch: str,
    state: str | None = None,
) -> str:
    """Find a merge request for a specific branch.

    This is useful when you know the branch name but not the review ID.

    Args:
        project: Project key (e.g., "ij")
        repository: Repository name (e.g., "ultimate")
        branch: Source branch name (e.g., "azhukova/QD-13281")
        state: Optional state filter: "Open", "Closed", or "Merged". Searches all states if not specified.

    Returns:
        Markdown with MR details if found, or a "not found" message.
    """
    client = get_client()
    result = await client.find_merge_request_by_branch(project, repository, branch, state=state)
    return format_find_result(result)


@mcp.tool()
@_handle_errors
async def create_merge_request(
    project: str,
    repository: str,
    source_branch: str,
    target_branch: str,
    title: str,
    description: str | None = None,
) -> str:
    """Create a new merge request.

    Args:
        project: Project key (e.g., "ij")
        repository: Repository name (e.g., "ultimate")
        source_branch: Branch with changes (e.g., "azhukova/fix-auth")
        target_branch: Branch to merge into (e.g., "master")
        title: MR title
        description: Optional MR description

    Returns:
        Markdown with created MR number, title, and branches.
    """
    client = get_client()
    result = await client.create_merge_request(
        project=project,
        repository=repository,
        source_branch=source_branch,
        target_branch=target_branch,
        title=title,
        description=description,
    )
    return format_create_result(result)


@mcp.tool()
@_handle_errors
async def close_merge_request(project: str, review_id: str) -> str:
    """Close a merge request.

    Args:
        project: Project key (e.g., "ij")
        review_id: MR number (e.g., "194108") or internal ID

    Returns:
        Confirmation message.
    """
    client = get_client()
    await client.set_merge_request_state(project, review_id, "Closed")
    return f"Merge request `{review_id}` closed."


@mcp.tool()
@_handle_errors
async def reopen_merge_request(project: str, review_id: str) -> str:
    """Reopen a closed merge request.

    The source branch must still exist. If it was deleted on close,
    re-push it before reopening.

    Args:
        project: Project key (e.g., "ij")
        review_id: MR number (e.g., "194108") or internal ID

    Returns:
        Confirmation message.
    """
    client = get_client()
    await client.set_merge_request_state(project, review_id, "Opened")
    return f"Merge request `{review_id}` reopened."


# Patronus tools =====


@mcp.tool()
@_handle_errors
async def get_patronus_robots(
    project: str,
    review_id: str,
) -> str:
    """Find Patronus robots (dry runs / safe merges) for a merge request.

    Use this to discover CI dry runs and safe merge attempts for a merge request.
    Each robot has an ID that can be passed to get_patronus_robot_details.

    Args:
        project: Project key (e.g., "ij")
        review_id: MR number (e.g., "194108")

    Returns:
        Markdown table of robots with IDs listed for follow-up queries.
    """
    client = get_client()
    mr = await client.get_merge_request(project, "", review_id)
    if not mr.branch_pairs:
        return "No branch pairs found on this merge request — cannot look up Patronus robots."
    source = mr.branch_pairs[0].source_branch
    target = mr.branch_pairs[0].target_branch

    patronus = get_patronus_client()
    result = await patronus.list_robots_for_review(
        project, review_id,
        source_branch=source, target_branch=target,
    )
    return format_patronus_robots(result)


@mcp.tool()
@_handle_errors
async def get_patronus_robot_details(robot_id: str) -> str:
    """Get details of a specific Patronus robot including TeamCity build checks and problems.

    Use the robot ID from get_patronus_robots or from a Patronus URL
    (e.g., https://patronus.labs.jb.gg/robot/<robot-id>).

    The returned TeamCity build IDs can be inspected further using the teamcity CLI:
        teamcity run view <build-id>

    Args:
        robot_id: Patronus robot UUID

    Returns:
        Markdown with robot overview, TeamCity checks table, and problems.
    """
    client = get_patronus_client()
    robot = await client.get_robot(robot_id)
    tc_checks = await client.get_robot_teamcity_checks(robot_id)
    problems = await client.get_robot_problems(robot_id)

    # Fetch attempt details for failed checks
    from ..models import AttemptDetails
    attempt_details: dict[str, AttemptDetails] = {}
    for check in tc_checks:
        if check.status != RunStatus.FAILURE:
            continue
        failed = [a for a in check.attempts if a.status == RunStatus.FAILURE]
        if not failed:
            continue
        attempt = failed[-1]
        if not attempt.id:
            continue
        try:
            details = await client.get_attempt_details(attempt.id)
            attempt_details[check.config.name] = details
        except Exception:
            pass  # Best-effort

    return format_patronus_robot_details(robot, tc_checks, problems, attempt_details)


@mcp.tool()
async def start_patronus_dry_run(
    project: str,
    review_id: str,
) -> str:
    """Start a Patronus dry run for a merge request.

    Runs all configured quality checks (TeamCity builds) without merging.
    Use get_patronus_robot_details to track progress.

    Args:
        project: Project key (e.g., "ij")
        review_id: MR number (e.g., "194108")

    Returns:
        Markdown with robot ID, Patronus URL, and status.
        On failure, returns actionable guidance on what to do next.
    """
    try:
        client = get_client()
        result = await client.start_safe_merge(project, review_id, operation="DryRun")
        return _format_safe_merge_result(result)
    except Exception as exc:
        msg = _format_error(exc)
        followup = await _check_dry_run_started(project, review_id)
        if followup:
            return f"{msg}\n\n{followup}"
        return f"{msg}\n\nNote: the dry run may have started despite this error. {_DRY_RUN_CHECK_HINT}"


async def _check_dry_run_started(project: str, review_id: str) -> str | None:
    """Check if a dry run robot exists for the given MR despite an error."""
    from ..patronus import extract_robot_ids

    try:
        client = get_client()
        items = await client.get_merge_request_discussions(project, "", review_id)
        text = "\n".join(
            item.text for item in items
            if isinstance(item, TimelineMessage)
        )
        robot_ids = extract_robot_ids(text)
        if not robot_ids:
            return None
        robot_id = robot_ids[-1]
        patronus = get_patronus_client()
        robot = await patronus.get_robot(robot_id)
        status = robot.status.value
        return (
            f"However, a dry run **is running** for this merge request "
            f"(robot `{robot_id}`, status: {status}). "
            f"Use `get_patronus_robot_details` with robot ID `{robot_id}` to track progress."
        )
    except Exception:
        return None


_DRY_RUN_CHECK_HINT = (
    "Use `get_patronus_robots` with the project and review ID to check the "
    "status of existing runs. Use `cancel_patronus_robot` to cancel a stuck "
    "run before retrying."
)


def _format_safe_merge_result(result: dict | list) -> str:
    """Format a Space safe-merge response into markdown."""
    if isinstance(result, list):
        errors = [e["message"] for e in result if e.get("type") == "Error"]
        if errors:
            joined = "; ".join(errors)
            if "already exists" in joined:
                return (
                    "**Dry run not started:** a dry run or merge is already "
                    "in progress for this merge request.\n\n" + _DRY_RUN_CHECK_HINT
                )
            if "secret" in joined.lower() and "not found" in joined.lower():
                secret_match = re.search(r"\$\{([^}]+)\}", joined)
                secret_name = secret_match.group(1) if secret_match else "safe.merge.patronus.starter.space.token"
                return (
                    f"**Dry run not started:** the project secret `{secret_name}` "
                    f"is not configured.\n\n"
                    f"To fix this, add the secret in Space project parameters:\n"
                    f"1. Ask the Patronus application owner to issue a permanent token "
                    f"from the Space Safe-Merge → Patronus Starter application\n"
                    f"2. Add it as a secret named `{secret_name}` in the project parameters"
                )
            if "not defined" in joined.lower() and "quality gate" in joined.lower():
                return (
                    "**Dry run not started:** safe merge is not configured for this repository.\n\n"
                    "To fix this:\n"
                    "1. Enable Quality Gates in the branch protection rules for the target branch\n"
                    "2. Enable Safe Merge and link a `.space/safe-merge.yaml` configuration file\n"
                    "3. The config file must be committed to the protected branch"
                )
            return f"**Dry run failed:** {joined}"
        progress = [e["message"] for e in result if e.get("type") == "Progress"]
        if progress:
            return "Dry run started.\n\n" + "\n".join(f"- {m}" for m in progress)
        return "Dry run started."

    parts: list[str] = ["Dry run started.\n"]
    if "jobId" in result:
        parts.append(f"**Job ID:** `{result['jobId']}`")
    if "robotId" in result:
        parts.append(f"**Robot ID:** `{result['robotId']}`")
    if "robotUrl" in result:
        parts.append(f"**Patronus:** {result['robotUrl']}")
    if "status" in result:
        parts.append(f"**Status:** {result['status']}")
    return "\n".join(parts) if len(parts) > 1 else "Dry run started."


@mcp.tool()
@_handle_errors
async def cancel_patronus_robot(robot_id: str) -> str:
    """Cancel a running Patronus robot (dry run or safe merge).

    Args:
        robot_id: Patronus robot UUID

    Returns:
        Confirmation message.
    """
    client = get_patronus_client()
    await client.cancel_robot(robot_id)
    return f"Cancellation requested for robot `{robot_id}`."


@mcp.tool()
@_handle_errors
async def download_attachment(attachment_id: str) -> str:
    """Download a file attachment from a Space MR discussion.

    Use the attachment ID from get_merge_request_discussions output
    (shown as [id: ...] next to each attachment).

    For text files, returns the file content directly.
    For binary files, returns the download URL.

    Args:
        attachment_id: Attachment UUID

    Returns:
        File content (text) or download URL (binary).
    """
    client = get_client()
    content, content_type = await client.download_attachment(attachment_id)

    if content_type and content_type.startswith("text/"):
        return content.decode("utf-8", errors="replace")

    size = _human_size(len(content))
    return (
        f"Binary file ({size}). "
        f"Download: https://jetbrains.team/d/{attachment_id}"
    )


def main():
    """Run the MCP server with stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
