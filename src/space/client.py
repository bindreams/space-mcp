from datetime import datetime, timezone
from typing import Any

import httpx


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

_FILE_ATTACHMENT_TYPES = {
    "FileAttachment": "file",
    "ImageAttachment": "image",
    "VideoAttachment": "video",
}


def _extract_attachments(msg: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract file/image/video attachments from a Space chat message.

    Filters out non-file types (UnfurlAttachment, DeletedAttachment, etc.).
    """
    result: list[dict[str, Any]] = []
    for att in msg.get("attachments") or []:
        details = att.get("details")
        if not details:
            continue
        class_name = details.get("className", "")
        att_type = _FILE_ATTACHMENT_TYPES.get(class_name)
        if not att_type:
            continue
        att_id = details.get("id", att.get("id", ""))
        result.append({
            "id": att_id,
            "type": att_type,
            "name": details.get("filename") or details.get("name") or "unnamed",
            "size_bytes": details.get("sizeBytes"),
            "width": details.get("width"),
            "height": details.get("height"),
            "download_url": f"https://jetbrains.team/d/{att_id}",
        })
    return result


_AUTHOR_TYPE_MAP = {
    "CUserPrincipalDetails": "user",
    "CApplicationPrincipalDetails": "app",
}


def _extract_author(msg: dict[str, Any]) -> dict[str, str | None]:
    """Extract author info from a Space chat message."""
    author_info = msg.get("author", {})
    details = author_info.get("details") or {}
    user_details = details.get("user", {})
    user_name = user_details.get("name", {})
    return {
        "username": user_details.get("username") or author_info.get("name"),
        "name": f"{user_name.get('firstName', '')} {user_name.get('lastName', '')}".strip()
            if user_name else author_info.get("name"),
        "author_type": _AUTHOR_TYPE_MAP.get(details.get("className")),
    }


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

    async def get_merge_request(self, project: str, repository: str, review_id: str) -> dict[str, Any]:
        """Get details of a specific merge request/code review.

        Args:
            project: Project key (e.g., "ij")
            repository: Repository name (e.g., "ultimate")
            review_id: Review identifier - numeric display number (e.g., "188120") or internal ID

        Returns:
            Dictionary with MR details including title, state, author, reviewers
        """
        # Space API uses 'number:' for display numbers and 'id:' for internal IDs
        # Numeric strings are display numbers, alphanumeric strings are internal IDs
        id_prefix = "number" if review_id.isdigit() else "id"
        url = f"{self.base_url}/api/http/projects/key:{project}/code-reviews/{id_prefix}:{review_id}"

        # Request specific fields using $fields parameter
        params = {
            "$fields": "id,number,title,description,state,createdBy(name,username),createdAt,participants(user(name,username),role,state),branchPairs(sourceBranch,targetBranch,repository(name))"
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            return response.json()

    async def get_merge_request_discussions(self, project: str, repository: str,
                                            review_id: str) -> list[dict[str, Any]]:
        """Get all discussions, comments, and timeline messages on a merge request.

        Returns code discussions (with file/line context), general timeline messages,
        and thread replies (e.g. Patronus dry run results attached to "started a dry run").

        Args:
            project: Project key
            repository: Repository name
            review_id: Review identifier

        Returns:
            List of items, each with a "type" field:
            - "code_discussion": has file, line, resolved, comments
            - "message": has text, author, created, and optionally thread_replies
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
                "author(name,details(className,user(username,name))),"
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
                # Next page starts after the last message's time (API expects ISO date)
                last_time = batch[-1].get("time")
                if last_time:
                    start_from = datetime.fromtimestamp(last_time / 1000, tz=timezone.utc).isoformat()
                else:
                    break

            # Process messages -----
            results: list[dict[str, Any]] = []
            for msg in all_msgs:
                details = msg.get("details") or {}
                code_disc = details.get("codeDiscussion")

                if code_disc:
                    results.append(await self._fetch_code_discussion(client, messages_url, code_disc))
                else:
                    text = msg.get("text")
                    if not text:
                        continue
                    item: dict[str, Any] = {
                        "type": "message",
                        "event_class": details.get("className"),
                        "text": text,
                        "author": _extract_author(msg),
                        "created": msg.get("time"),
                    }
                    attachments = _extract_attachments(msg)
                    if attachments:
                        item["attachments"] = attachments
                    # Fetch thread replies (dry runs, safe merges, etc.)
                    thread_id = (msg.get("thread") or {}).get("id")
                    if thread_id:
                        item["thread_replies"] = await self._fetch_thread_replies(
                            client, messages_url, thread_id,
                        )
                    results.append(item)

            return results

    async def _fetch_code_discussion(
        self, client: httpx.AsyncClient, messages_url: str, code_disc: dict[str, Any],
    ) -> dict[str, Any]:
        """Fetch a code discussion's comment thread."""
        disc_channel_id = (code_disc.get("channel") or {}).get("id")
        anchor = code_disc.get("anchor") or {}

        thread_messages = []
        if disc_channel_id:
            thread_fields = (
                "messages(id,text,"
                "author(name,details(className,user(username,name))),"
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
                    comment: dict[str, Any] = {
                        "text": text,
                        "author": _extract_author(thread_msg),
                        "created": thread_msg.get("time"),
                    }
                    attachments = _extract_attachments(thread_msg)
                    if attachments:
                        comment["attachments"] = attachments
                    thread_messages.append(comment)

        return {
            "type": "code_discussion",
            "id": code_disc.get("id"),
            "file": anchor.get("filename"),
            "line": anchor.get("line"),
            "resolved": code_disc.get("resolved", False),
            "comments": thread_messages,
        }

    async def _fetch_thread_replies(
        self, client: httpx.AsyncClient, messages_url: str, thread_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch replies in a message thread (dry runs, safe merges, etc.)."""
        reply_fields = (
            "messages(id,text,"
            "author(name,details(className,user(username,name))),"
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
            return []

        replies = []
        for msg in response.json().get("messages", []):
            text = msg.get("text")
            if not text:
                continue
            reply: dict[str, Any] = {
                "text": text,
                "author": _extract_author(msg),
                "created": msg.get("time"),
            }
            attachments = _extract_attachments(msg)
            if attachments:
                reply["attachments"] = attachments
            replies.append(reply)
        return replies

    async def download_attachment(
        self, attachment_id: str,
    ) -> tuple[bytes, str | None]:
        """Download an attachment by ID.

        Args:
            attachment_id: Attachment UUID from the Space API

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

    async def list_merge_requests(
        self,
        project: str,
        repository: str,
        branch: str | None = None,
        state: str | None = None,
        limit: int = 20,
        text: str | None = None,
    ) -> list[dict[str, Any]]:
        """List merge requests for a repository.

        Args:
            project: Project key
            repository: Repository name
            branch: Optional source branch filter (client-side)
            state: Optional state filter (Open, Closed, Merged)
            limit: Maximum number of results
            text: Optional text search (server-side, searches title/branch/etc)

        Returns:
            List of MRs with basic info
        """
        url = f"{self.base_url}/api/http/projects/key:{project}/code-reviews"

        params: dict[str, Any] = {
            "$fields": "data(review(id,title,state,createdBy(name,username),createdAt,branchPairs(sourceBranch,targetBranch,repository(name))))",
            "type": "MergeRequest",
            "$top": limit,
        }

        # Add filters if provided - map user-friendly state names to API values
        if state:
            state_map = {"Open": "Opened", "Closed": "Closed", "Merged": "Merged"}
            params["state"] = state_map.get(state, state)

        # Server-side text search (more efficient for large projects)
        if text:
            params["text"] = text

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            data = response.json()
            # Extract review objects from the wrapper structure
            reviews = [item.get("review", item) for item in data.get("data", [])]

            # Filter by repository if specified (client-side filtering)
            # repository(name) returns {"name": "..."} object from the API
            if repository:
                def matches_repository(bp: dict) -> bool:
                    repo = bp.get("repository")
                    if isinstance(repo, dict):
                        return repo.get("name") == repository
                    return repo == repository  # fallback for string format

                reviews = [
                    r for r in reviews if any(
                        matches_repository(bp)
                        for bp in r.get("branchPairs", [])
                    )
                ]

            # Filter by branch if specified (client-side filtering)
            if branch:
                reviews = [
                    r for r in reviews if any(bp.get("sourceBranch") == branch for bp in r.get("branchPairs", []))
                ]

            return reviews

    async def start_safe_merge(
        self,
        project: str,
        review_id: str,
        operation: str = "DryRun",
        squash_commit_message: str | None = None,
        delete_source_branch: bool = False,
    ) -> dict[str, Any]:
        """Start a safe merge or dry run via the Space API.

        Space orchestrates the full flow: creates a merge branch, triggers
        Patronus checks, and posts timeline events on the merge request.

        The MergeSelectOptions schema (from space-dotnet-sdk generated DTOs) requires:
        - operation: MergeSelectOptionsOperation — DryRun | Merge | Rebase
        - mergeMode: GitMergeMode — FF | FF_ONLY | NO_FF
        - rebaseMode: GitRebaseMode — FF | NO_FF
        - squashMode: GitSquashMode — ALL | AUTO | NONE
        - squashCommitMessage: string
        - deleteSourceBranch: bool
        - targetStatusesForLinkedIssues: list

        Args:
            project: Project key (e.g., "ij")
            review_id: Internal MR id (alphanumeric) or display number (numeric)
            operation: One of DryRun, Merge, Rebase
            squash_commit_message: Commit message when squashMode is ALL
            delete_source_branch: Delete source branch after merge (default False)

        Returns:
            Response dict from Space (contents depend on the operation).
        """
        # Resolve numeric display numbers to internal IDs
        internal_id = review_id
        if review_id.isdigit():
            mr = await self.get_merge_request(project, "", review_id)
            internal_id = mr["id"]

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
                detail = response.text or response.reason_phrase
                raise httpx.HTTPStatusError(
                    f"{response.status_code}: {detail}",
                    request=response.request,
                    response=response,
                )
            # Space may return empty body on success
            if not response.text:
                return {}
            return response.json()

    async def set_merge_request_state(
        self,
        project: str,
        review_id: str,
        state: str,
    ) -> None:
        """Change the state of a merge request (close or reopen).

        Args:
            project: Project key (e.g., "ij")
            review_id: Review identifier - numeric display number or internal ID
            state: Target state: "Opened" or "Closed"
        """
        id_prefix = "number" if review_id.isdigit() else "id"
        url = f"{self.base_url}/api/http/projects/key:{project}/code-reviews/{id_prefix}:{review_id}/state"

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                url,
                headers={**self._headers(), "Content-Type": "application/json"},
                json={"state": state},
            )
            if not response.is_success:
                detail = response.text or response.reason_phrase
                raise httpx.HTTPStatusError(
                    f"{response.status_code}: {detail}",
                    request=response.request,
                    response=response,
                )

    async def create_merge_request(
        self,
        project: str,
        repository: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a new merge request.

        Args:
            project: Project key (e.g., "ij")
            repository: Repository name (e.g., "ultimate")
            source_branch: Branch with changes
            target_branch: Branch to merge into
            title: MR title
            description: Optional MR description

        Returns:
            Dictionary with created MR details (id, number, title, etc.)
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
            "$fields": "id,number,title,state,branchPairs(sourceBranch,targetBranch,repository(name))"
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={**self._headers(), "Content-Type": "application/json"},
                json=body,
                params=params,
            )
            if not response.is_success:
                detail = response.text or response.reason_phrase
                raise httpx.HTTPStatusError(
                    f"{response.status_code}: {detail}",
                    request=response.request,
                    response=response,
                )
            return response.json()

    async def find_merge_request_by_branch(
        self, project: str, repository: str, branch: str, state: str | None = None,
    ) -> dict[str, Any] | None:
        """Find a merge request for a specific branch.

        Args:
            project: Project key
            repository: Repository name
            branch: Source branch name
            state: Optional state filter (Open, Closed, Merged). Searches all states if None.

        Returns:
            MR details if found, None otherwise
        """
        # Use server-side text search with branch name for efficiency
        # Then filter client-side for exact branch match and repository
        reviews = await self.list_merge_requests(
            project=project,
            repository=repository,
            branch=branch,
            state=state,
            limit=50,
            text=branch,  # Server-side search by branch name
        )

        if reviews:
            # Return the first matching review (most recent)
            return await self.get_merge_request(project, repository, reviews[0]["id"])

        return None
