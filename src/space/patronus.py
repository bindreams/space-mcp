import re
from typing import Any

import httpx


_ROBOT_UUID_RE = re.compile(
    r"/robot/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)


def extract_robot_ids(text: str) -> list[str]:
    """Extract unique Patronus robot UUIDs from text containing robot URLs.

    Looks for URLs like https://patronus.labs.jb.gg/robot/<uuid>.
    Returns deduplicated list in order of first appearance.
    """
    seen: set[str] = set()
    result: list[str] = []
    for match in _ROBOT_UUID_RE.finditer(text):
        uuid = match.group(1)
        if uuid not in seen:
            seen.add(uuid)
            result.append(uuid)
    return result


class PatronusClient:
    """Client for Patronus REST API.

    Uses Space token for authentication via the /app/rest/ prefix.
    See https://youtrack.jetbrains.com/articles/PAT-A-11 for API reference.
    """

    def __init__(self, token: str, base_url: str = "https://patronus.labs.jb.gg"):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    async def list_robots(
        self,
        repository: str | None = None,
        source_branch: str | None = None,
        target_branch: str | None = None,
    ) -> list[dict[str, Any]]:
        """List Patronus robots, optionally filtered.

        Note: ``repository`` is the Patronus **alias** (from ServiceConfig.kt),
        NOT the Space repository name.  These may differ, and a single Space
        repo can map to multiple aliases.  When looking up robots for a known
        merge request, prefer :meth:`list_robots_for_review` instead.

        Args:
            repository: Patronus alias (optional). Omit when alias is unknown.
            source_branch: Original source branch name filter (optional).
            target_branch: Target branch filter (optional).

        Returns:
            List of RobotOverviewDto dicts.
        """
        url = f"{self.base_url}/app/rest/v1/robots"
        params: dict[str, str] = {}
        if repository:
            params["repository"] = repository
        if source_branch:
            params["sourceBranch"] = source_branch
        if target_branch:
            params["targetBranch"] = target_branch

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("robots", [])

    async def list_robots_for_review(
        self,
        project: str,
        review_number: int | str,
        source_branch: str | None = None,
        target_branch: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find Patronus robots for a Space merge request.

        Queries without the ``repository`` filter (which requires the Patronus
        alias) and matches results client-side by ``spaceReviewUrl``.

        At least one of *source_branch* or *target_branch* must be provided to
        avoid an unfiltered query across all robots in the org.

        Args:
            project: Space project key (e.g., ``"space-mcp"``).
            review_number: MR display number (e.g., ``86``).
            source_branch: Original source branch name (optional).
            target_branch: Target branch name (optional).

        Returns:
            List of RobotOverviewDto dicts whose ``spaceReviewUrl`` matches.
        """
        if not source_branch and not target_branch:
            raise ValueError("At least one of source_branch or target_branch is required")

        robots = await self.list_robots(
            source_branch=source_branch, target_branch=target_branch,
        )

        # Match by spaceReviewUrl containing /p/{project}/reviews/{number}
        # followed by / or end-of-string (to avoid /reviews/86 matching /reviews/860)
        review_re = re.compile(
            rf"/p/{re.escape(project)}/reviews/{review_number}(/|$)", re.IGNORECASE,
        )
        return [
            r for r in robots
            if review_re.search(r.get("spaceReviewUrl") or "")
        ]

    async def get_robot(self, robot_id: str) -> dict[str, Any]:
        """Get overview of a specific Patronus robot.

        Args:
            robot_id: Robot UUID

        Returns:
            RobotOverviewDto dict
        """
        url = f"{self.base_url}/app/rest/v1/robots/{robot_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            return response.json()

    async def get_robot_teamcity_checks(self, robot_id: str) -> list[dict[str, Any]]:
        """Get TeamCity check statuses for a Patronus robot.

        Args:
            robot_id: Robot UUID

        Returns:
            List of TeamCity check dicts with name, status, buildId, buildUrl
        """
        url = f"{self.base_url}/app/rest/v1/robots/{robot_id}/teamcity-checks"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            data = response.json()
            # API returns {"robotId": "...", "teamCityChecks": [...]} wrapper
            if isinstance(data, dict):
                return data.get("teamCityChecks", [])
            return data

    async def get_robot_problems(self, robot_id: str) -> dict[str, Any]:
        """Get problems/failures for a Patronus robot.

        Args:
            robot_id: Robot UUID

        Returns:
            Dict with robotId and list of problems (each with title and optional detailsMarkdown)
        """
        url = f"{self.base_url}/app/rest/v1/robots/{robot_id}/problems"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            return response.json()

    async def get_attempt_details(self, attempt_id: str) -> dict[str, Any]:
        """Get details of a specific TeamCity check attempt including failed tests and builds.

        Args:
            attempt_id: Attempt UUID

        Returns:
            Dict with attempt details including failedTests and failedBuilds
        """
        url = f"{self.base_url}/app/rest/v1/teamcity-checks/attempts/{attempt_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            return response.json()

    # Write operations ===========================================================

    async def cancel_robot(self, robot_id: str) -> None:
        """Cancel a running Patronus robot.

        Args:
            robot_id: Robot UUID
        """
        url = f"{self.base_url}/app/rest/v1/robots/{robot_id}/cancel"

        async with httpx.AsyncClient() as client:
            response = await client.put(url, headers=self._headers())
            response.raise_for_status()

    async def get_me(self, repository: str) -> dict[str, Any]:
        """Get the current user's identity from the Patronus API.

        Extracts the 'me' field from the robots list response.

        Args:
            repository: Repository name (needed for the robots endpoint)

        Returns:
            RobotOwnerDto with type, id, name, email
        """
        url = f"{self.base_url}/app/rest/v1/robots"
        params = {"repository": repository}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("me", {})
