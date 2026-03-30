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


_USER_PROFILE_URL = "https://jetbrains.team/api/http/team-directory/profiles/me"
_APP_PROFILE_URL = "https://jetbrains.team/api/http/applications/me"


async def validate_token(token: str) -> dict[str, Any]:
    """Validate a Space token (personal access token or application token).

    Tries the user profile endpoint first. On 403 (which applications get
    because they are not in the team directory), falls back to the
    application endpoint.

    Returns:
        For user tokens: ``{"kind": "user", "username": ..., "name": {...}, "emails": [...]}``.
        For app tokens: ``{"kind": "app", "name": ...}``.

    Raises:
        httpx.HTTPStatusError: If the token is invalid or both endpoints fail.
    """
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            _USER_PROFILE_URL,
            headers=headers,
            params={"$fields": "username,name(firstName,lastName),emails(email)"},
        )
        if user_resp.is_success:
            result = user_resp.json()
            result["kind"] = "user"
            return result

        if user_resp.status_code != 403:
            user_resp.raise_for_status()

        app_resp = await client.get(
            _APP_PROFILE_URL,
            headers=headers,
            params={"$fields": "name"},
        )
        if app_resp.is_success:
            data = app_resp.json()
            return {"kind": "app", "name": data.get("name", data.get("clientId", "unknown"))}

        app_resp.raise_for_status()
        raise AssertionError("unreachable")  # raise_for_status always raises on non-2xx


class SpaceClient:
    """Client for JetBrains Space HTTP API."""

    def __init__(self, token: str | None):
        self.base_url = "https://jetbrains.team"
        self.token = token
        self._http: httpx.AsyncClient | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token is not None:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                headers=self._headers(),
                follow_redirects=True,
                timeout=15.0,
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def warmup(self) -> None:
        """Establish TCP+TLS connection to the server (best-effort)."""
        try:
            await self.http.head(self.base_url)
        except httpx.HTTPError:
            pass

    async def __aenter__(self) -> "SpaceClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Make an authenticated async HTTP request."""
        url = f"{self.base_url}{path}"
        return await self.http.request(method, url, **kwargs)

    # MR operations ====================================================================================================

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
            "branchPair(sourceBranch,targetBranch,repository(name))"
        }

        response = await self.http.get(url, params=params)
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
        author: str | None = None,
    ) -> list[MergeRequest]:
        """List merge requests, paginating to ensure complete results.

        Paginates through the Space API and applies client-side filters
        for repository, branch, and author (not supported server-side).

        Args:
            project: Project key
            repository: Repository name
            branch: Optional source branch filter (client-side exact match)
            state: Optional state filter (Open, Closed, Merged). None queries all states.
            limit: Maximum number of results
            text: Optional server-side text search. NOT auto-derived from
                  branch — text search may return incomplete results.
            author: Optional author username filter (client-side, case-insensitive)

        Returns:
            List of MergeRequests with basic info, sorted by creation date (newest first).
        """
        # Space API requires explicit state — query each state separately when None
        if not state:
            all_reviews: list[MergeRequest] = []
            for s in ("Open", "Closed", "Merged"):
                remaining = limit - len(all_reviews)
                if remaining <= 0:
                    break
                batch = await self.list_merge_requests(
                    project,
                    repository,
                    branch,
                    s,
                    remaining,
                    text,
                    author,
                )
                all_reviews.extend(batch)
            all_reviews.sort(key=lambda mr: mr.created_at, reverse=True)
            return all_reviews[:limit]

        url = f"{self.base_url}/api/http/projects/key:{project}/code-reviews"

        params: dict[str, Any] = {
            "$fields": "data(review(id,number,title,state,"
            "createdBy(id,name,username),"
            "createdAt,"
            "branchPair(sourceBranch,targetBranch,repository(name))))",
            "type": "MergeRequest",
        }

        state_map = {"Open": "Opened", "Closed": "Closed", "Merged": "Merged"}
        params["state"] = state_map.get(state, state)

        if text:
            params["text"] = text

        async def fetch_page(skip: int, top: int) -> list[dict]:
            resp = await self.http.get(
                url,
                params={**params, "$top": top, "$skip": skip},
            )
            resp.raise_for_status()
            data = resp.json()
            return [item.get("review", item) for item in data.get("data", [])]

        def matches(review: dict) -> bool:
            bp = review.get("branchPair")
            if repository and (not bp or not _matches_repository(bp, repository)):
                return False
            if branch and (not bp or bp.get("sourceBranch") != branch):
                return False
            if author:
                created_by = review.get("createdBy") or {}
                username = created_by.get("username") or ""
                if username.lower() != author.lower():
                    return False
            return True

        reviews = await paginated_fetch(
            fetch_page,
            filter_fn=matches,
            limit=limit,
        )
        return [await MergeRequest.from_api(r, self) for r in reviews]

    async def find_merge_request_by_branch(
        self,
        project: str,
        repository: str,
        branch: str,
        state: str | None = None,
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
            "branchPair(sourceBranch,targetBranch,repository(name))"
        }

        response = await self.http.post(url, json=body, params=params)
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

        response = await self.http.post(url, json=body)
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

        response = await self.http.patch(url, json={"state": state})
        if not response.is_success:
            detail = _error_detail(response)
            raise httpx.HTTPStatusError(
                f"{response.status_code}: {detail}",
                request=response.request,
                response=response,
            )

    # Comments / discussions ===========================================================================================

    async def get_feed_channel(self, project: str, review_id: str) -> str | None:
        """Get the feed channel ID for a merge request.

        Returns:
            Channel ID string, or None if the MR has no feed channel.
        """
        id_prefix = "number" if review_id.isdigit() else "id"
        path = f"/api/http/projects/key:{project}/code-reviews/{id_prefix}:{review_id}"
        resp = await self.request("GET", path, params={"$fields": "feedChannel(id)"})
        resp.raise_for_status()
        return resp.json().get("feedChannel", {}).get("id")

    async def post_comment(
        self,
        project: str,
        review_id: str,
        text: str,
        thread_message_id: str | None = None,
    ) -> str:
        """Post a general comment on a merge request's feed channel.

        Args:
            project: Project key (e.g., "ij")
            review_id: MR number or internal ID
            text: Comment text (Markdown supported)
            thread_message_id: If provided, posts as a thread reply to this message

        Returns:
            The posted message ID.

        Raises:
            ValueError: If the MR has no feed channel.
            httpx.HTTPStatusError: On API errors.
        """
        channel_id = await self.get_feed_channel(project, review_id)
        if not channel_id:
            raise ValueError(f"MR {review_id} has no feed channel")

        body: dict[str, Any] = {
            "content": {"className": "ChatMessage.Text", "text": text},
        }
        if thread_message_id:
            body["channel"] = f"message:{thread_message_id}"
        else:
            body["channel"] = f"id:{channel_id}"

        resp = await self.request(
            "POST",
            "/api/http/chats/messages/send-message",
            json=body,
            params={"$fields": "id"},
        )
        resp.raise_for_status()
        return resp.json()["id"]

    async def create_code_discussion(
        self,
        project: str,
        review_id: str,
        repository: str,
        revision: str,
        filename: str,
        line: int,
        text: str,
    ) -> str:
        """Create an inline code discussion on a merge request.

        Args:
            project: Project key
            review_id: MR number or internal ID
            repository: Repository name
            revision: Git commit SHA
            filename: File path
            line: Line number (new side)
            text: Comment text

        Returns:
            The discussion's channel ID (for posting follow-up replies).
        """
        id_prefix = "number" if review_id.isdigit() else "id"
        body = {
            "text": text,
            "repository": repository,
            "reviewId": f"{id_prefix}:{review_id}",
            "pending": False,
            "anchor": {
                "revision": revision,
                "filename": filename,
                "line": line,
            },
        }
        resp = await self.request(
            "POST",
            f"/api/http/projects/key:{project}/code-reviews/code-discussions",
            json=body,
            params={"$fields": "channel(id)"},
        )
        resp.raise_for_status()
        return resp.json()["channel"]["id"]

    async def reply_to_discussion(self, discussion_channel_id: str, text: str) -> None:
        """Post a reply in a code discussion's channel.

        Args:
            discussion_channel_id: Channel ID of the code discussion
            text: Reply text
        """
        resp = await self.request(
            "POST",
            "/api/http/chats/messages/send-message",
            json={
                "channel": f"id:{discussion_channel_id}",
                "content": {"className": "ChatMessage.Text", "text": text},
            },
        )
        resp.raise_for_status()

    # Timeline / discussions ===========================================================================================

    async def get_merge_request_discussions(self, project: str, repository: str, review_id: str) -> list[TimelineItem]:
        """Get all discussions, comments, and timeline messages on a merge request."""
        from .discussions import fetch_discussions
        return await fetch_discussions(self, project, repository, review_id)

    # Attachments ======================================================================================================

    async def download_attachment(
        self,
        attachment_id: str,
    ) -> tuple[bytes, str | None]:
        """Download an attachment by ID.

        Returns:
            Tuple of (content_bytes, content_type).
        """
        url = f"{self.base_url}/d/{attachment_id}"
        response = await self.http.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type")
        return response.content, content_type
