from typing import Any

import httpx

from .models import (
    BranchPair,
    MergeRequest,
    TimelineItem,
)
from .pagination import paginated_fetch


def _matches_repository(bp: dict, repository: str) -> bool:
    """Check if a branch-pair dict matches the given repository name."""
    repo = bp.get("repository")
    if isinstance(repo, dict):
        return repo.get("name") == repository
    return repo == repository


def _error_detail(response: httpx.Response) -> str:
    """Extract a non-empty error description from an HTTP response."""
    return response.text or response.reason_phrase or f"HTTP {response.status_code}"


async def validate_token(token: str) -> dict[str, Any]:
    """Validate a Space PAT by fetching the current user's profile.

    Returns:
        Dict with 'username' and 'emails' (list of {email: str}).

    Raises:
        httpx.HTTPStatusError: If the token is invalid or API error.
    """
    url = "https://jetbrains.team/api/http/team-directory/profiles/me"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"$fields": "username,emails(email)"}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()


class SpaceClient:
    """Client for JetBrains Space HTTP API."""

    def __init__(self, token: str):
        self.base_url = "https://jetbrains.team"
        self.token = token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Make an authenticated async HTTP request."""
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient() as client:
            return await client.request(method, url, headers=self._headers(), **kwargs)

    # MR operations =====

    async def get_merge_request(self, project: str, repository: str, review_id: str) -> MergeRequest:
        """Get details of a specific merge request/code review.

        Args:
            project: Project key (e.g., "ij")
            repository: Repository name (e.g., "ultimate")
            review_id: Review identifier - numeric display number (e.g., "188120") or internal ID

        Returns:
            MergeRequest with title, state, author, reviewers, branches.
        """
        id_prefix = "number" if review_id.isdigit() else "id"
        url = f"{self.base_url}/api/http/projects/key:{project}/code-reviews/{id_prefix}:{review_id}"

        params = {
            "$fields": "id,number,title,description,state,"
                       "createdBy(id,name,username),"
                       "createdAt,"
                       "participants(user(id,name,username),role,state),"
                       "branchPairs(sourceBranch,targetBranch,repository(name))"
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            return await MergeRequest.from_api(response.json(), self)

    async def list_merge_requests(
        self,
        project: str,
        repository: str,
        branch: str | None = None,
        state: str | None = None,
        limit: int = 20,
        text: str | None = None,
    ) -> list[MergeRequest]:
        """List merge requests, paginating to ensure complete results.

        Paginates through the Space API and applies client-side filters
        for repository and branch (not supported server-side).

        Args:
            project: Project key
            repository: Repository name
            branch: Optional source branch filter (client-side exact match)
            state: Optional state filter (Open, Closed, Merged)
            limit: Maximum number of results
            text: Optional server-side text search. NOT auto-derived from
                  branch — text search may return incomplete results.

        Returns:
            List of MergeRequests with basic info.
        """
        url = f"{self.base_url}/api/http/projects/key:{project}/code-reviews"

        params: dict[str, Any] = {
            "$fields": "data(review(id,number,title,state,"
                       "createdBy(id,name,username),"
                       "createdAt,"
                       "branchPairs(sourceBranch,targetBranch,repository(name))))",
            "type": "MergeRequest",
        }

        if state:
            state_map = {"Open": "Opened", "Closed": "Closed", "Merged": "Merged"}
            params["state"] = state_map.get(state, state)

        if text:
            params["text"] = text

        headers = self._headers()

        async def fetch_page(skip: int, top: int) -> list[dict]:
            async with httpx.AsyncClient() as http:
                resp = await http.get(
                    url, headers=headers,
                    params={**params, "$top": top, "$skip": skip},
                )
                resp.raise_for_status()
                data = resp.json()
                return [item.get("review", item) for item in data.get("data", [])]

        def matches(review: dict) -> bool:
            pairs = review.get("branchPairs", [])
            if repository and not any(
                _matches_repository(bp, repository) for bp in pairs
            ):
                return False
            if branch and not any(
                bp.get("sourceBranch") == branch for bp in pairs
            ):
                return False
            return True

        reviews = await paginated_fetch(
            fetch_page, filter_fn=matches, limit=limit,
        )
        return [await MergeRequest.from_api(r, self) for r in reviews]

    async def find_merge_request_by_branch(
        self, project: str, repository: str, branch: str, state: str | None = None,
    ) -> MergeRequest | None:
        """Find a merge request for a specific branch.

        Uses text search for speed (narrows server results), with a full-scan
        fallback in case text search doesn't index the branch name.

        Args:
            project: Project key
            repository: Repository name
            branch: Source branch name
            state: Optional state filter (Open, Closed, Merged). Searches all states if None.

        Returns:
            MergeRequest if found, None otherwise.
        """
        # Fast path: text search narrows API results
        reviews = await self.list_merge_requests(
            project=project,
            repository=repository,
            branch=branch,
            state=state,
            limit=1,
            text=branch,
        )
        if not reviews:
            # Fallback: text search may not index this branch — full scan
            reviews = await self.list_merge_requests(
                project=project,
                repository=repository,
                branch=branch,
                state=state,
                limit=1,
            )

        if reviews:
            return await self.get_merge_request(project, repository, reviews[0].id)

        return None

    async def create_merge_request(
        self,
        project: str,
        repository: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str | None = None,
    ) -> MergeRequest:
        """Create a new merge request.

        Args:
            project: Project key (e.g., "ij")
            repository: Repository name (e.g., "ultimate")
            source_branch: Branch with changes
            target_branch: Branch to merge into
            title: MR title
            description: Optional MR description

        Returns:
            MergeRequest with created MR details.
        """
        url = f"{self.base_url}/api/http/projects/key:{project}/code-reviews/merge-requests"

        body: dict[str, Any] = {
            "repository": repository,
            "sourceBranch": source_branch,
            "targetBranch": target_branch,
            "title": title,
        }
        if description is not None:
            body["description"] = description

        params = {
            "$fields": "id,number,title,state,createdAt,"
                       "branchPairs(sourceBranch,targetBranch,repository(name))"
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={**self._headers(), "Content-Type": "application/json"},
                json=body,
                params=params,
            )
            if not response.is_success:
                detail = _error_detail(response)
                raise httpx.HTTPStatusError(
                    f"{response.status_code}: {detail}",
                    request=response.request,
                    response=response,
                )
            return await MergeRequest.from_api(response.json(), self)

    async def start_safe_merge(
        self,
        project: str,
        review_id: str,
        operation: str = "DryRun",
        squash_commit_message: str | None = None,
        delete_source_branch: bool = False,
    ) -> dict[str, Any]:
        """Start a safe merge or dry run via the Space API.

        Returns:
            Response dict from Space (contents depend on the operation).
        """
        internal_id = review_id
        if review_id.isdigit():
            mr = await self.get_merge_request(project, "", review_id)
            internal_id = mr.id

        url = f"{self.base_url}/api/http/projects/key:{project}/code-reviews/safe-merge"
        merge_options: dict[str, Any] = {
            "operation": operation,
            "mergeMode": "FF",
            "rebaseMode": "FF",
            "squashMode": "NONE",
            "squashCommitMessage": squash_commit_message or "",
            "deleteSourceBranch": delete_source_branch,
            "targetStatusesForLinkedIssues": [],
        }

        body = {
            "mergeRequestId": f"id:{internal_id}",
            "mergeOptions": merge_options,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={**self._headers(), "Content-Type": "application/json"},
                json=body,
            )
            if not response.is_success:
                detail = _error_detail(response)
                raise httpx.HTTPStatusError(
                    f"{response.status_code}: {detail}",
                    request=response.request,
                    response=response,
                )
            if not response.text:
                return {}
            return response.json()

    async def set_merge_request_state(
        self,
        project: str,
        review_id: str,
        state: str,
    ) -> None:
        """Change the state of a merge request (close or reopen)."""
        id_prefix = "number" if review_id.isdigit() else "id"
        url = f"{self.base_url}/api/http/projects/key:{project}/code-reviews/{id_prefix}:{review_id}/state"

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                url,
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"state": state},
            )
            if not response.is_success:
                detail = _error_detail(response)
                raise httpx.HTTPStatusError(
                    f"{response.status_code}: {detail}",
                    request=response.request,
                    response=response,
                )

    # Timeline / discussions =====

    async def get_merge_request_discussions(self, project: str, repository: str,
                                            review_id: str) -> list[TimelineItem]:
        """Get all discussions, comments, and timeline messages on a merge request."""
        from .discussions import fetch_discussions
        return await fetch_discussions(self, project, repository, review_id)

    # Attachments =====

    async def download_attachment(
        self, attachment_id: str,
    ) -> tuple[bytes, str | None]:
        """Download an attachment by ID.

        Returns:
            Tuple of (content_bytes, content_type).
        """
        url = f"{self.base_url}/d/{attachment_id}"
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers=self._headers(), follow_redirects=True,
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type")
            return response.content, content_type
