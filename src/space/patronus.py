from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

import httpx

from .models import (
    AttemptDetails,
    PatronusCheckRun,
    PatronusRun,
    Problem,
)

if TYPE_CHECKING:
    from .client import SpaceClient


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

    def __init__(
        self,
        token: str,
        base_url: str = "https://patronus.labs.jb.gg",
        space_client: SpaceClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.space_client = space_client

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    def _require_space_client(self) -> SpaceClient:
        if self.space_client is None:
            raise RuntimeError(
                "PatronusClient requires a SpaceClient reference to resolve "
                "account details. Pass space_client= at construction time."
            )
        return self.space_client

    # Robot operations =====

    async def list_robots(
        self,
        repository: str | None = None,
        source_branch: str | None = None,
        target_branch: str | None = None,
    ) -> list[PatronusRun]:
        """List Patronus robots, optionally filtered.

        Returns:
            List of PatronusRun instances.
        """
        space = self._require_space_client()
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
            return [
                await PatronusRun.from_api(r, space)
                for r in data.get("robots", [])
            ]

    async def list_robots_for_review(
        self,
        project: str,
        review_number: int | str,
        source_branch: str | None = None,
        target_branch: str | None = None,
    ) -> list[PatronusRun]:
        """Find Patronus robots for a Space merge request.

        Queries without the ``repository`` filter and matches results
        client-side by ``spaceReviewUrl``.
        """
        if not source_branch and not target_branch:
            raise ValueError("At least one of source_branch or target_branch is required")

        # Fetch raw dicts for client-side filtering before model conversion
        space = self._require_space_client()
        url = f"{self.base_url}/app/rest/v1/robots"
        params: dict[str, str] = {}
        if source_branch:
            params["sourceBranch"] = source_branch
        if target_branch:
            params["targetBranch"] = target_branch

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            raw_robots = response.json().get("robots", [])

        # Filter on raw dicts (before model conversion)
        review_re = re.compile(
            rf"/p/{re.escape(project)}/reviews/{review_number}(/|$)", re.IGNORECASE,
        )
        matched = [
            r for r in raw_robots
            if review_re.search(r.get("spaceReviewUrl") or "")
        ]

        return [await PatronusRun.from_api(r, space) for r in matched]

    async def get_robot(self, robot_id: str) -> PatronusRun:
        """Get overview of a specific Patronus robot.

        Returns:
            PatronusRun instance.
        """
        space = self._require_space_client()
        url = f"{self.base_url}/app/rest/v1/robots/{robot_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            return await PatronusRun.from_api(response.json(), space)

    # Check operations =====

    async def get_robot_teamcity_checks(self, robot_id: str) -> list[PatronusCheckRun]:
        """Get TeamCity check statuses for a Patronus robot.

        Returns:
            List of PatronusCheckRun instances.
        """
        url = f"{self.base_url}/app/rest/v1/robots/{robot_id}/teamcity-checks"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            data = response.json()
            raw_checks = data.get("teamCityChecks", []) if isinstance(data, dict) else data
            return [PatronusCheckRun.from_api(c) for c in raw_checks]

    async def get_robot_problems(self, robot_id: str) -> tuple[Problem, ...]:
        """Get problems/failures for a Patronus robot.

        Returns raw Problem shells (title + details only). For enriched
        Problems with failed tests/builds, combine with attempt details
        at the caller level.
        """
        url = f"{self.base_url}/app/rest/v1/robots/{robot_id}/problems"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            data = response.json()
            problems = data.get("problems", []) if isinstance(data, dict) else []
            return tuple(
                Problem(
                    title=p.get("title", ""),
                    details=p.get("detailsMarkdown"),
                )
                for p in problems
            )

    async def get_attempt_details(self, attempt_id: str) -> AttemptDetails:
        """Get details of a specific TeamCity check attempt.

        Returns:
            AttemptDetails with failed tests and builds.
        """
        url = f"{self.base_url}/app/rest/v1/teamcity-checks/attempts/{attempt_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            return AttemptDetails.from_api(response.json())

    # Write operations =====

    async def cancel_robot(self, robot_id: str) -> None:
        """Cancel a running Patronus robot."""
        url = f"{self.base_url}/app/rest/v1/robots/{robot_id}/cancel"

        async with httpx.AsyncClient() as client:
            response = await client.put(url, headers=self._headers())
            response.raise_for_status()

    async def get_me(self, repository: str) -> dict[str, Any]:
        """Get the current user's identity from the Patronus API.

        Returns:
            RobotOwnerDto dict with type, id, name, email.
            Caller converts to SpaceAccount if needed.
        """
        url = f"{self.base_url}/app/rest/v1/robots"
        params = {"repository": repository}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("me", {})
