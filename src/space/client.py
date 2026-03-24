from datetime import datetime, timezone
from typing import Any

import httpx

from .models import (
    BranchPair,
    CodeDiscussion,
    Comment,
    MergeRequest,
    SpaceAccount,
    SpaceApp,
    SpacePrincipal,
    TimelineEventClass,
    TimelineItem,
    TimelineMessage,
    parse_attachments,
)
from .models.space import _epoch_ms_to_datetime


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


_ATTACHMENT_FIELDS = (
    "attachments(id,details(className,id,filename,sizeBytes,name,width,height))"
)


async def _resolve_author(msg: dict[str, Any], client: "SpaceClient") -> SpacePrincipal:
    """Resolve a Space chat message author to a SpacePrincipal."""
    author_info = msg.get("author", {})
    details = author_info.get("details") or {}
    class_name = details.get("className", "")

    if class_name == "CUserPrincipalDetails":
        user_details = details.get("user", {})
        user_id = user_details.get("id")
        if user_id:
            return await SpaceAccount.from_id(client, user_id)
        # User principal without id — resolve by username if available
        username = user_details.get("username")
        if username:
            return await SpaceAccount.from_username(client, username)
        # Last resort: unknown user (should not happen with correct $fields)
        raise ValueError(f"CUserPrincipalDetails missing both id and username: {author_info}")

    if class_name == "CApplicationPrincipalDetails":
        return SpaceApp(app_name=author_info.get("name", "App"))

    # Fallback for unknown principal types
    return SpaceApp(app_name=author_info.get("name", "Unknown"))


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
        """List merge requests for a repository.

        Args:
            project: Project key
            repository: Repository name
            branch: Optional source branch filter (client-side)
            state: Optional state filter (Open, Closed, Merged)
            limit: Maximum number of results
            text: Optional text search (server-side, searches title/branch/etc)

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
            "$top": limit,
        }

        if state:
            state_map = {"Open": "Opened", "Closed": "Closed", "Merged": "Merged"}
            params["state"] = state_map.get(state, state)

        if text:
            params["text"] = text

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            data = response.json()
            reviews = [item.get("review", item) for item in data.get("data", [])]

            # Client-side filtering on raw dicts BEFORE model conversion
            if repository:
                def matches_repository(bp: dict) -> bool:
                    repo = bp.get("repository")
                    if isinstance(repo, dict):
                        return repo.get("name") == repository
                    return repo == repository

                reviews = [
                    r for r in reviews if any(
                        matches_repository(bp)
                        for bp in r.get("branchPairs", [])
                    )
                ]

            if branch:
                reviews = [
                    r for r in reviews if any(
                        bp.get("sourceBranch") == branch
                        for bp in r.get("branchPairs", [])
                    )
                ]

            # Convert to models after filtering
            return [await MergeRequest.from_api(r, self) for r in reviews]

    async def find_merge_request_by_branch(
        self, project: str, repository: str, branch: str, state: str | None = None,
    ) -> MergeRequest | None:
        """Find a merge request for a specific branch.

        Args:
            project: Project key
            repository: Repository name
            branch: Source branch name
            state: Optional state filter (Open, Closed, Merged). Searches all states if None.

        Returns:
            MergeRequest if found, None otherwise.
        """
        reviews = await self.list_merge_requests(
            project=project,
            repository=repository,
            branch=branch,
            state=state,
            limit=50,
            text=branch,
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
        """Get all discussions, comments, and timeline messages on a merge request.

        Returns:
            List of CodeDiscussion and TimelineMessage instances.
        """
        id_prefix = "number" if review_id.isdigit() else "id"
        review_url = f"{self.base_url}/api/http/projects/key:{project}/code-reviews/{id_prefix}:{review_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                review_url,
                headers=self._headers(),
                params={"$fields": "feedChannel(id)"}
            )
            response.raise_for_status()
            review = response.json()

            channel_id = review.get("feedChannel", {}).get("id")
            if not channel_id:
                return []

            messages_url = f"{self.base_url}/api/http/chats/messages"
            feed_fields = (
                "messages(id,text,"
                "author(name,details(className,user(id,username,name))),"
                f"time,thread(id),{_ATTACHMENT_FIELDS},"
                "details(className,"
                "codeDiscussion(id,resolved,channel(id),"
                "anchor(filename,line))))"
            )

            # Paginate: fetch all feed messages -----
            all_msgs: list[dict[str, Any]] = []
            start_from: str | None = None
            while True:
                params: dict[str, str] = {
                    "channel": f"id:{channel_id}",
                    "sorting": "FromOldestToNewest",
                    "batchSize": "50",
                    "$fields": feed_fields,
                }
                if start_from:
                    params["startFromDate"] = start_from
                response = await client.get(messages_url, headers=self._headers(), params=params)
                response.raise_for_status()
                batch = response.json().get("messages", [])
                if not batch:
                    break
                all_msgs.extend(batch)
                if len(batch) < 50:
                    break
                last_time = batch[-1].get("time")
                if last_time:
                    start_from = datetime.fromtimestamp(last_time / 1000, tz=timezone.utc).isoformat()
                else:
                    break

            # Process messages -----
            results: list[TimelineItem] = []
            for msg in all_msgs:
                details = msg.get("details") or {}
                code_disc = details.get("codeDiscussion")

                if code_disc:
                    results.append(await self._fetch_code_discussion(client, messages_url, code_disc))
                else:
                    text = msg.get("text")
                    if not text:
                        continue
                    author = await _resolve_author(msg, self)
                    created_at = _epoch_ms_to_datetime(msg["time"]) if msg.get("time") else datetime.now(tz=timezone.utc)
                    attachments = parse_attachments(msg)

                    thread_replies: tuple[Comment, ...] = ()
                    thread_id = (msg.get("thread") or {}).get("id")
                    if thread_id:
                        thread_replies = await self._fetch_thread_replies(client, messages_url, thread_id)

                    results.append(TimelineMessage(
                        event_class=TimelineEventClass(details.get("className", "Unknown")),
                        text=text,
                        author=author,
                        created_at=created_at,
                        attachments=attachments,
                        thread_replies=thread_replies,
                    ))

            return results

    async def _fetch_code_discussion(
        self, client: httpx.AsyncClient, messages_url: str, code_disc: dict[str, Any],
    ) -> CodeDiscussion:
        """Fetch a code discussion's comment thread."""
        disc_channel_id = (code_disc.get("channel") or {}).get("id")
        anchor = code_disc.get("anchor") or {}

        comments: list[Comment] = []
        if disc_channel_id:
            thread_fields = (
                "messages(id,text,"
                "author(name,details(className,user(id,username,name))),"
                f"time,{_ATTACHMENT_FIELDS})"
            )
            thread_params = {
                "channel": f"id:{disc_channel_id}",
                "sorting": "FromOldestToNewest",
                "batchSize": "50",
                "$fields": thread_fields,
            }
            thread_response = await client.get(
                messages_url, headers=self._headers(), params=thread_params,
            )
            if thread_response.status_code == 200:
                for thread_msg in thread_response.json().get("messages", []):
                    text = thread_msg.get("text")
                    if not text:
                        continue
                    author = await _resolve_author(thread_msg, self)
                    created_at = _epoch_ms_to_datetime(thread_msg["time"]) if thread_msg.get("time") else datetime.now(tz=timezone.utc)
                    comments.append(Comment(
                        text=text,
                        author=author,
                        created_at=created_at,
                        attachments=parse_attachments(thread_msg),
                    ))

        return CodeDiscussion(
            id=code_disc.get("id", ""),
            file=anchor.get("filename"),
            line=anchor.get("line"),
            resolved=code_disc.get("resolved", False),
            comments=tuple(comments),
        )

    async def _fetch_thread_replies(
        self, client: httpx.AsyncClient, messages_url: str, thread_id: str,
    ) -> tuple[Comment, ...]:
        """Fetch replies in a message thread (dry runs, safe merges, etc.)."""
        reply_fields = (
            "messages(id,text,"
            "author(name,details(className,user(id,username,name))),"
            f"time,{_ATTACHMENT_FIELDS})"
        )
        params = {
            "channel": f"id:{thread_id}",
            "sorting": "FromOldestToNewest",
            "batchSize": "50",
            "$fields": reply_fields,
        }
        response = await client.get(
            messages_url, headers=self._headers(), params=params,
        )
        if response.status_code != 200:
            return ()

        replies: list[Comment] = []
        for msg in response.json().get("messages", []):
            text = msg.get("text")
            if not text:
                continue
            author = await _resolve_author(msg, self)
            created_at = _epoch_ms_to_datetime(msg["time"]) if msg.get("time") else datetime.now(tz=timezone.utc)
            replies.append(Comment(
                text=text,
                author=author,
                created_at=created_at,
                attachments=parse_attachments(msg),
            ))
        return tuple(replies)

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
