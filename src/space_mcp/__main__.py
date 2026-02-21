import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import SpaceClient

# Initialize MCP server
mcp = FastMCP("space", json_response=True)

# Lazy-initialize client (allows server to start even without token for tools/list)
_client: SpaceClient | None = None


def get_client() -> SpaceClient:
    """Get or create the Space client."""
    global _client
    if _client is None:
        token = os.environ.get("SPACE_TOKEN")
        if not token:
            raise ValueError("SPACE_TOKEN environment variable is required")
        _client = SpaceClient(token)
    return _client


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
    """Get all comments and discussions on a merge request.

    Args:
        project: Project key (e.g., "ij")
        repository: Repository name (e.g., "ultimate")
        review_id: Review/MR identifier

    Returns:
        JSON array of discussions with author, text, file/line context, and replies
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
async def find_merge_request_by_branch(project: str, repository: str, branch: str) -> str:
    """Find an open merge request for a specific branch.

    This is useful when you know the branch name but not the review ID.

    Args:
        project: Project key (e.g., "ij")
        repository: Repository name (e.g., "ultimate")
        branch: Source branch name (e.g., "azhukova/QD-13281")

    Returns:
        JSON with MR details if found, or null if no open MR exists for the branch
    """
    client = get_client()
    result = await client.find_merge_request_by_branch(project, repository, branch)
    return json.dumps(result, indent=2, default=str)


def main():
    """Run the MCP server with stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
