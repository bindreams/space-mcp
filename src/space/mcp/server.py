from mcp.server.fastmcp import FastMCP

from ..clients import get_client, get_patronus_client
from ..context import AuthenticationError
from .format import (
    format_merge_request,
    format_find_result,
    format_discussions,
    format_merge_request_list,
    format_patronus_robots,
    format_patronus_robot_details,
)

# Initialize MCP server
mcp = FastMCP("space")

_AUTH_ERROR_MSG = (
    "**Authentication required.** Set the `SPACE_TOKEN` environment variable "
    "or run `space auth login` to store credentials."
)


@mcp.tool()
async def get_merge_request(project: str, repository: str, review_id: str) -> str:
    """Get details of a specific merge request.

    Args:
        project: Project key (e.g., "ij" for IntelliJ)
        repository: Repository name (e.g., "ultimate")
        review_id: Review/MR identifier (numeric ID or full review ID)

    Returns:
        Markdown with MR title, state, author, branches, and reviewer table.
    """
    try:
        client = get_client()
    except AuthenticationError:
        return _AUTH_ERROR_MSG
    result = await client.get_merge_request(project, repository, review_id)
    return format_merge_request(result)


@mcp.tool()
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
    try:
        client = get_client()
    except AuthenticationError:
        return _AUTH_ERROR_MSG
    result = await client.get_merge_request_discussions(project, repository, review_id)
    return format_discussions(result)


@mcp.tool()
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
    try:
        client = get_client()
    except AuthenticationError:
        return _AUTH_ERROR_MSG
    result = await client.list_merge_requests(
        project=project,
        repository=repository,
        branch=branch,
        state=state,
        limit=limit,
    )
    return format_merge_request_list(result)


@mcp.tool()
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
    try:
        client = get_client()
    except AuthenticationError:
        return _AUTH_ERROR_MSG
    result = await client.find_merge_request_by_branch(project, repository, branch, state=state)
    return format_find_result(result)


# Patronus tools =============================================================


@mcp.tool()
async def get_patronus_robots(
    repository: str,
    source_branch: str,
    target_branch: str | None = None,
) -> str:
    """Find Patronus robots (dry runs / safe merges) for a branch.

    Use this to discover CI dry runs and safe merge attempts for a merge request.
    Each robot has an ID that can be passed to get_patronus_robot_details.

    Args:
        repository: Repository name (e.g., "ultimate")
        source_branch: Source branch name (e.g., "azhukova/fix-auth")
        target_branch: Optional target branch filter (e.g., "master")

    Returns:
        Markdown table of robots with IDs listed for follow-up queries.
    """
    try:
        client = get_patronus_client()
    except AuthenticationError:
        return _AUTH_ERROR_MSG
    result = await client.list_robots(
        repository=repository,
        source_branch=source_branch,
        target_branch=target_branch,
    )
    return format_patronus_robots(result)


@mcp.tool()
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
    try:
        client = get_patronus_client()
    except AuthenticationError:
        return _AUTH_ERROR_MSG
    robot = await client.get_robot(robot_id)
    tc_checks = await client.get_robot_teamcity_checks(robot_id)
    problems = await client.get_robot_problems(robot_id)

    # Fetch attempt details for failed checks to surface test/build failure info
    attempt_details: dict[str, dict] = {}
    for check in tc_checks:
        if check.get("status") != "FAILURE":
            continue
        attempts = check.get("attempts", [])
        # Find the latest failed attempt
        failed = [a for a in attempts if a.get("status") == "FAILURE"]
        if not failed:
            continue
        attempt = failed[-1]
        attempt_id = attempt.get("id")
        if not attempt_id:
            continue
        try:
            details = await client.get_attempt_details(attempt_id)
            attempt_details[check.get("name", "")] = details
        except Exception:
            pass  # Best-effort: don't fail if attempt details are unavailable

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
    """
    try:
        client = get_client()
    except AuthenticationError:
        return _AUTH_ERROR_MSG
    result = await client.start_safe_merge(project, review_id, operation="DryRun")
    return f"Dry run started.\n\n{_format_safe_merge_result(result)}"


def _format_safe_merge_result(result: dict) -> str:
    """Format a Space safe-merge response into markdown."""
    parts: list[str] = []
    if "jobId" in result:
        parts.append(f"**Job ID:** `{result['jobId']}`")
    if "robotId" in result:
        parts.append(f"**Robot ID:** `{result['robotId']}`")
    if "robotUrl" in result:
        parts.append(f"**Patronus:** {result['robotUrl']}")
    if "status" in result:
        parts.append(f"**Status:** {result['status']}")
    return "\n".join(parts) if parts else "Request accepted."


@mcp.tool()
async def cancel_patronus_robot(robot_id: str) -> str:
    """Cancel a running Patronus robot (dry run or safe merge).

    Args:
        robot_id: Patronus robot UUID

    Returns:
        Confirmation message.
    """
    try:
        client = get_patronus_client()
    except AuthenticationError:
        return _AUTH_ERROR_MSG
    await client.cancel_robot(robot_id)
    return f"Cancellation requested for robot `{robot_id}`."


def main():
    """Run the MCP server with stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
