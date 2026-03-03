from typing import Any

import httpx


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
        repository: str,
        source_branch: str | None = None,
        target_branch: str | None = None,
    ) -> list[dict[str, Any]]:
        """List Patronus robots for a repository, optionally filtered by branch.

        Args:
            repository: Repository name (e.g., "ultimate")
            source_branch: Optional source branch filter
            target_branch: Optional target branch filter

        Returns:
            List of RobotOverviewDto dicts
        """
        url = f"{self.base_url}/app/rest/v1/robots"
        params: dict[str, str] = {"repository": repository}
        if source_branch:
            params["sourceBranch"] = source_branch
        if target_branch:
            params["targetBranch"] = target_branch

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("robots", [])

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
