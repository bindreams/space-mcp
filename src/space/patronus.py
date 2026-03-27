from __future__ import annotations

import asyncio
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

_RUN_UUID_RE = re.compile(r"/robot/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")


def extract_run_ids(text: str) -> list[str]:
    """Extract unique Patronus run UUIDs from text containing run URLs.

    Looks for URLs like https://patronus.labs.jb.gg/robot/<uuid>.
    Returns deduplicated list in order of first appearance.
    """
    seen: set[str] = set()
    result: list[str] = []
    for match in _RUN_UUID_RE.finditer(text):
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
        token: str | None,
        base_url: str = "https://patronus.labs.jb.gg",
        space_client: SpaceClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.space_client = space_client

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token is not None:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _require_space_client(self) -> SpaceClient:
        if self.space_client is None:
            raise RuntimeError(
                "PatronusClient requires a SpaceClient reference to resolve "
                "account details. Pass space_client= at construction time."
            )
        return self.space_client

    # Run operations ===================================================================================================

    async def list_runs(
        self,
        repository: str | None = None,
        source_branch: str | None = None,
        target_branch: str | None = None,
    ) -> list[PatronusRun]:
        """List Patronus runs, optionally filtered.

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
            return [await PatronusRun.from_api(r, space) for r in data.get("robots", [])]

    async def list_runs_for_review(
        self,
        project: str,
        review_number: int | str,
        source_branch: str | None = None,
        target_branch: str | None = None,
    ) -> list[PatronusRun]:
        """Find Patronus runs for a Space merge request.

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
            raw_entries = response.json().get("robots", [])

        # Filter on raw dicts (before model conversion)
        review_re = re.compile(
            rf"/p/{re.escape(project)}/reviews/{review_number}(/|$)",
            re.IGNORECASE,
        )
        matched = [r for r in raw_entries if review_re.search(r.get("spaceReviewUrl") or "")]

        return [await PatronusRun.from_api(r, space) for r in matched]

    async def get_run(self, run_id: str) -> PatronusRun:
        """Get overview of a specific Patronus run.

        Returns:
            PatronusRun instance.
        """
        space = self._require_space_client()
        url = f"{self.base_url}/app/rest/v1/robots/{run_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            return await PatronusRun.from_api(response.json(), space)

    # Check operations =================================================================================================

    async def get_run_teamcity_checks(self, run_id: str) -> list[PatronusCheckRun]:
        """Get TeamCity check statuses for a Patronus run.

        Returns:
            List of PatronusCheckRun instances.
        """
        url = f"{self.base_url}/app/rest/v1/robots/{run_id}/teamcity-checks"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            data = response.json()
            raw_checks = data.get("teamCityChecks", []) if isinstance(data, dict) else data
            return [PatronusCheckRun.from_api(c) for c in raw_checks]

    async def get_run_problems(self, run_id: str) -> tuple[Problem, ...]:
        """Get problems/failures for a Patronus run.

        Returns raw Problem shells (title + details only). For enriched
        Problems with failed tests/builds, combine with attempt details
        at the caller level.
        """
        url = f"{self.base_url}/app/rest/v1/robots/{run_id}/problems"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            data = response.json()
            problems = data.get("problems", []) if isinstance(data, dict) else []
            return tuple(Problem(
                title=p.get("title", ""),
                details=p.get("detailsMarkdown"),
            ) for p in problems)

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

    async def get_run_changes(self, run_id: str) -> list[dict[str, Any]]:
        """Get the commits delivered by a specific Patronus run.

        Returns:
            List of commit dicts with 'hash', 'subjectMarkdown', and 'url' keys.
        """
        url = f"{self.base_url}/app/rest/v1/robots/{run_id}/changes"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers())
            response.raise_for_status()
            data = response.json()
            return data.get("topCommits", [])

    # Write operations =================================================================================================

    async def cancel_run(self, run_id: str) -> None:
        """Cancel a running Patronus run."""
        url = f"{self.base_url}/app/rest/v1/robots/{run_id}/cancel"

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


# Check fetching helpers ===============================================================================================


async def fetch_checks_for_active(
    patronus: PatronusClient,
    runs: list[PatronusRun],
) -> dict[str, list[PatronusCheckRun]]:
    """Fetch TeamCity checks for active runs, returning {run_id: checks}.

    Only fetches for runs with an active status (RUNNING, PENDING, STARTING).
    API errors are silently dropped — the run falls back to its raw status.
    Concurrency is limited to 5 parallel requests.
    """
    from .models.status import ACTIVE_STATUSES

    active = [r for r in runs if r.status in ACTIVE_STATUSES]
    if not active:
        return {}

    sem = asyncio.Semaphore(5)

    async def _fetch(r: PatronusRun) -> list[PatronusCheckRun]:
        async with sem:
            return await patronus.get_run_teamcity_checks(r.id)

    results = await asyncio.gather(*(_fetch(r) for r in active), return_exceptions=True)
    checks_by_run: dict[str, list[PatronusCheckRun]] = {}
    for r, result in zip(active, results):
        if not isinstance(result, Exception):
            checks_by_run[r.id] = result
    return checks_by_run
