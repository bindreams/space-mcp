from __future__ import annotations

import asyncio
import functools
import re

import httpx
from mcp.server.fastmcp import FastMCP

from ..clients import get_client, get_patronus_client
from ..auth import AuthenticationError
from ..models import RunStatus, TimelineMessage
from ..patronus import fetch_checks_for_active
from ..formatting import human_size
from .format import (
    format_merge_request,
    format_create_result,
    format_discussions,
    format_merge_request_list,
    format_patronus_runs,
    format_patronus_run_details,
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
        except Exception as exc:  # MCP error boundary: tools must never raise
            return _format_error(exc)
    return wrapper


@mcp.tool(name="get_merge_request", title="Get Merge Request")
@_handle_errors
async def get_merge_request(project: str, repository: str, review_id: str) -> str:
    """Get details of a specific merge request.

    Args:
        project: Project key (e.g., "ij" for IntelliJ)
        repository: Repository name (e.g., "ultimate")
        review_id: Review/MR identifier (numeric ID or full review ID)

    Returns:
        YAML with MR title, state, author, branches, and reviewers.
    """
    client = get_client()
    result = await client.get_merge_request(project, repository, review_id)
    return format_merge_request(result)


@mcp.tool(name="get_merge_request_timeline", title="Get Merge Request Timeline")
@_handle_errors
async def get_merge_request_timeline(project: str, repository: str, review_id: str) -> str:
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


@mcp.tool(name="get_merge_requests", title="Find Merge Requests")
@_handle_errors
async def get_merge_requests(
    project: str,
    repository: str,
    branch: str | None = None,
    state: str | None = None,
    limit: int = 20,
    author: str | None = None,
) -> str:
    """List merge requests for a repository.

    Args:
        project: Project key (e.g., "ij")
        repository: Repository name (e.g., "ultimate")
        branch: Optional source branch name to filter by
        state: Optional state filter: "Open", "Closed", or "Merged"
        limit: Maximum number of results (default 20)
        author: Optional author username to filter by (case-insensitive)

    Returns:
        YAML list of merge requests.
    """
    client = get_client()
    result = await client.list_merge_requests(
        project=project,
        repository=repository,
        branch=branch,
        state=state,
        limit=limit,
        author=author,
    )
    return format_merge_request_list(result)


@mcp.tool(name="put_merge_request", title="Create Merge Request")
@_handle_errors
async def put_merge_request(
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
        YAML with created MR number, title, and branches.
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


@mcp.tool(name="post_close_merge_request", title="Close Merge Request")
@_handle_errors
async def post_close_merge_request(project: str, review_id: str) -> str:
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


@mcp.tool(name="post_reopen_merge_request", title="Reopen Merge Request")
@_handle_errors
async def post_reopen_merge_request(project: str, review_id: str) -> str:
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


# Comment / discussion tools =====


@mcp.tool(name="post_merge_request_comment", title="Comment on Merge Request")
@_handle_errors
async def post_merge_request_comment(project: str, review_id: str, text: str) -> str:
    """Post a general comment on a merge request.

    Args:
        project: Project key (e.g., "ij")
        review_id: MR number (e.g., "194108") or internal ID
        text: Comment text (Markdown supported)

    Returns:
        Confirmation message.
    """
    client = get_client()
    await client.post_comment(project, review_id, text)
    return f"Comment posted on MR `{review_id}`."


@mcp.tool(name="post_code_discussion", title="Create Code Discussion")
@_handle_errors
async def post_code_discussion(
    project: str,
    review_id: str,
    repository: str,
    revision: str,
    filename: str,
    line: int,
    text: str,
) -> str:
    """Create an inline code discussion on a specific file and line of a merge request.

    Args:
        project: Project key (e.g., "ij")
        review_id: MR number (e.g., "194108") or internal ID
        repository: Repository name (e.g., "ultimate")
        revision: Git commit SHA the comment is anchored to
        filename: File path (e.g., "src/main.py")
        line: Line number (new side of the diff)
        text: Comment text (Markdown supported)

    Returns:
        Confirmation with file and line reference.
    """
    client = get_client()
    await client.create_code_discussion(
        project, review_id, repository, revision, filename, line, text,
    )
    return f"Code discussion created on `{filename}:{line}`."


@mcp.tool(name="post_reply_to_code_discussion", title="Reply to Code Discussion")
@_handle_errors
async def post_reply_to_code_discussion(
    project: str,
    review_id: str,
    discussion_channel_id: str,
    text: str,
) -> str:
    """Reply to an existing code discussion on a merge request.

    The discussion_channel_id can be found in the timeline output of a merge request.

    Args:
        project: Project key (for context only)
        review_id: MR number (for context only)
        discussion_channel_id: Channel ID of the code discussion to reply to
        text: Reply text (Markdown supported)

    Returns:
        Confirmation message.
    """
    client = get_client()
    await client.reply_to_discussion(discussion_channel_id, text)
    return "Reply posted."


@mcp.tool(name="post_delete_merge_request", title="Delete Merge Request")
@_handle_errors
async def post_delete_merge_request(project: str, review_id: str) -> str:
    """Delete a merge request.

    Args:
        project: Project key (e.g., "ij")
        review_id: MR number (e.g., "194108") or internal ID

    Returns:
        Confirmation message.
    """
    client = get_client()
    await client.set_merge_request_state(project, review_id, "Deleted")
    return f"Merge request `{review_id}` deleted."


# Patronus tools =====


@mcp.tool(name="get_patronus_runs", title="List Patronus Runs")
@_handle_errors
async def get_patronus_runs(
    project: str,
    review_id: str,
) -> str:
    """Find Patronus runs (dry runs / safe merges) for a merge request.

    Use this to discover CI dry runs and safe merge attempts for a merge request.
    Each run has an ID that can be passed to get_patronus_run.

    Args:
        project: Project key (e.g., "ij")
        review_id: MR number (e.g., "194108")

    Returns:
        YAML list of runs with IDs for follow-up queries.
    """
    client = get_client()
    mr = await client.get_merge_request(project, "", review_id)
    if not mr.branch_pair:
        return "No branch pair found on this merge request — cannot look up Patronus runs."
    source = mr.branch_pair.source_branch
    target = mr.branch_pair.target_branch

    patronus = get_patronus_client()
    result = await patronus.list_runs_for_review(
        project, review_id,
        source_branch=source, target_branch=target,
    )
    commits: dict[str, str | None] = {}
    changes_list = await asyncio.gather(
        *(patronus.get_run_changes(r.id) for r in result),
        return_exceptions=True,
    )
    for r, ch in zip(result, changes_list):
        if isinstance(ch, Exception) or not ch:
            commits[r.id] = None
        else:
            commits[r.id] = ch[-1].get("hash", "")[:8]

    # Fetch checks for active runs to derive effective status
    checks_by_run = await fetch_checks_for_active(patronus, result)
    # ty doesn't recognize list as a subtype of Sequence in dict values (covariance)
    return format_patronus_runs(result, commits, checks=checks_by_run or None)  # ty: ignore[invalid-argument-type]


@mcp.tool(name="get_patronus_run", title="Get Patronus Run")
@_handle_errors
async def get_patronus_run(run_id: str) -> str:
    """Get details of a specific Patronus run including TeamCity build checks and problems.

    Use the run ID from get_patronus_runs or from a Patronus URL
    (e.g., https://patronus.labs.jb.gg/robot/<run-id>).

    The returned TeamCity build IDs can be inspected further using the teamcity CLI:
        teamcity run view <build-id>

    Args:
        run_id: Patronus run UUID

    Returns:
        YAML with run overview, TeamCity checks, and problems.
    """
    client = get_patronus_client()
    run = await client.get_run(run_id)
    tc_checks = await client.get_run_teamcity_checks(run_id)
    problems = await client.get_run_problems(run_id)

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
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException):
            pass  # best-effort: omit details if Patronus is unreachable

    return format_patronus_run_details(run, tc_checks, problems, attempt_details)


@mcp.tool(name="put_patronus_dry_run", title="Start Patronus Dry Run")
async def put_patronus_dry_run(
    project: str,
    review_id: str,
) -> str:
    """Start a Patronus dry run for a merge request.

    Runs all configured quality checks (TeamCity builds) without merging.
    Use get_patronus_run to track progress.

    Args:
        project: Project key (e.g., "ij")
        review_id: MR number (e.g., "194108")

    Returns:
        Markdown with run ID, Patronus URL, and status.
        On failure, returns actionable guidance on what to do next.
    """
    try:
        client = get_client()
        result = await client.start_safe_merge(project, review_id, operation="DryRun")
        return _format_safe_merge_result(result)
    except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException, AuthenticationError) as exc:
        msg = _format_error(exc)
        followup = await _check_dry_run_started(project, review_id)
        if followup:
            return f"{msg}\n\n{followup}"
        return f"{msg}\n\nNote: the dry run may have started despite this error. {_DRY_RUN_CHECK_HINT}"


async def _check_dry_run_started(project: str, review_id: str) -> str | None:
    """Check if a dry run exists for the given MR despite an error."""
    from ..patronus import extract_run_ids

    try:
        client = get_client()
        items = await client.get_merge_request_discussions(project, "", review_id)
        text = "\n".join(
            item.text for item in items
            if isinstance(item, TimelineMessage)
        )
        run_ids = extract_run_ids(text)
        if not run_ids:
            return None
        run_id = run_ids[-1]
        patronus = get_patronus_client()
        run = await patronus.get_run(run_id)
        status = run.status.value
        return (
            f"However, a dry run **is running** for this merge request "
            f"(run `{run_id}`, status: {status}). "
            f"Use `get_patronus_run` with run ID `{run_id}` to track progress."
        )
    except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException, KeyError):
        return None  # best-effort followup check


_DRY_RUN_CHECK_HINT = (
    "Use `get_patronus_runs` with the project and review ID to check the "
    "status of existing runs. Use `post_cancel_patronus_run` to cancel a stuck "
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
        parts.append(f"**Run ID:** `{result['robotId']}`")
    if "robotUrl" in result:
        parts.append(f"**Patronus:** {result['robotUrl']}")
    if "status" in result:
        parts.append(f"**Status:** {result['status']}")
    return "\n".join(parts) if len(parts) > 1 else "Dry run started."


@mcp.tool(name="post_cancel_patronus_run", title="Cancel Patronus Run")
@_handle_errors
async def post_cancel_patronus_run(run_id: str) -> str:
    """Cancel a running Patronus run (dry run or safe merge).

    Args:
        run_id: Patronus run UUID

    Returns:
        Confirmation message.
    """
    client = get_patronus_client()
    await client.cancel_run(run_id)
    return f"Cancellation requested for run `{run_id}`."


@mcp.tool(name="get_attachment", title="Download Attachment")
@_handle_errors
async def get_attachment(attachment_id: str) -> str:
    """Download a file attachment from a Space MR discussion.

    Use the attachment ID from get_merge_request_timeline output
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

    size = human_size(len(content))
    return (
        f"Binary file ({size}). "
        f"Download: https://jetbrains.team/d/{attachment_id}"
    )


def main():
    """Run the MCP server with stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
