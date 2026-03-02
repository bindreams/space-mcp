import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import SpaceClient
from .patronus import PatronusClient

# Initialize MCP server
mcp = FastMCP("space", json_response=True)

# Lazy-initialize clients (allows server to start even without token for tools/list)
_client: SpaceClient | None = None
_patronus_client: PatronusClient | None = None


def get_client() -> SpaceClient:
    """Get or create the Space client."""
    global _client
    if _client is None:
        token = os.environ.get("SPACE_TOKEN")
        if not token:
            raise ValueError("SPACE_TOKEN environment variable is required")
        _client = SpaceClient(token)
    return _client


def get_patronus_client() -> PatronusClient:
    """Get or create the Patronus client. Reuses SPACE_TOKEN for auth."""
    global _patronus_client
    if _patronus_client is None:
        token = os.environ.get("SPACE_TOKEN")
        if not token:
            raise ValueError("SPACE_TOKEN environment variable is required")
        _patronus_client = PatronusClient(token)
    return _patronus_client


@mcp.tool()
async def get_merge_request(project: str, repository: str, review_id: str) -> str:
    """Get details of a specific merge request.

    Args:
        project: Project key (e.g., "ij" for IntelliJ)
        repository: Repository name (e.g., "ultimate")
        review_id: Review/MR identifier (numeric ID or full review ID)

    Returns:
        JSON with MR details: title, state, author, reviewers, branches
    """
    client = get_client()
    result = await client.get_merge_request(project, repository, review_id)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def get_merge_request_discussions(project: str, repository: str, review_id: str) -> str:
    """Get all comments, discussions, and timeline messages on a merge request.

    Returns both code discussions (with file/line context) and general timeline
    messages (including bot messages like Patronus dry run results).

    Args:
        project: Project key (e.g., "ij")
        repository: Repository name (e.g., "ultimate")
        review_id: Review/MR identifier

    Returns:
        JSON array of items, each with a "type" field:
        - "code_discussion": has file, line, resolved, comments
        - "message": has text, author, created (general timeline messages)
    """
    client = get_client()
    result = await client.get_merge_request_discussions(project, repository, review_id)
    return json.dumps(result, indent=2, default=str)


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
        JSON array of MRs with id, title, state, author, and branches
    """
    client = get_client()
    result = await client.list_merge_requests(
        project=project,
        repository=repository,
        branch=branch,
        state=state,
        limit=limit,
    )
    return json.dumps(result, indent=2, default=str)


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
        JSON with MR details if found, or null if no MR exists for the branch
    """
    client = get_client()
    result = await client.find_merge_request_by_branch(project, repository, branch, state=state)
    return json.dumps(result, indent=2, default=str)


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
        JSON array of robots with id, name, status, pushMode, branches, and timestamps.
        Status is one of: RUNNING, FAILING, SUCCESSFUL, FAILED, CANCELED.
        pushMode is one of: DRY_RUN, REBASE, etc.
    """
    client = get_patronus_client()
    result = await client.list_robots(
        repository=repository,
        source_branch=source_branch,
        target_branch=target_branch,
    )
    return json.dumps(result, indent=2, default=str)


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
        JSON with robot overview, teamcity_checks (build statuses/URLs), and problems.
    """
    client = get_patronus_client()
    robot = await client.get_robot(robot_id)
    tc_checks = await client.get_robot_teamcity_checks(robot_id)
    problems = await client.get_robot_problems(robot_id)

    result = {
        "robot": robot,
        "teamcity_checks": tc_checks,
        "problems": problems,
    }
    return json.dumps(result, indent=2, default=str)


def main():
    """Run the MCP server with stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
