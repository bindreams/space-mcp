from mcp.server.fastmcp import FastMCP

from ..clients import get_client, get_patronus_client
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
    client = get_client()
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
    client = get_client()
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
    client = get_patronus_client()
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
    client = get_patronus_client()
    robot = await client.get_robot(robot_id)
    tc_checks = await client.get_robot_teamcity_checks(robot_id)
    problems = await client.get_robot_problems(robot_id)
    return format_patronus_robot_details(robot, tc_checks, problems)


def main():
    """Run the MCP server with stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
