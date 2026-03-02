from typing import Any

import httpx


def _extract_author(msg: dict[str, Any]) -> dict[str, str | None]:
    """Extract author info from a Space chat message."""
    author_info = msg.get("author", {})
    user_details = (author_info.get("details") or {}).get("user", {})
    user_name = user_details.get("name", {})
    return {
        "username": user_details.get("username") or author_info.get("name"),
        "name": f"{user_name.get('firstName', '')} {user_name.get('lastName', '')}".strip()
            if user_name else author_info.get("name"),
    }


class SpaceClient:
    """Client for JetBrains Space HTTP API."""

    def __init__(self, token: str, base_url: str = "https://jetbrains.team"):
        self.base_url = base_url.rstrip("/")
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
            "$fields": "id,title,state,createdBy(name,username),createdAt,participants(user(name,username),role,state),branchPairs(sourceBranch,targetBranch,repository(name))"
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            return response.json()

    async def get_merge_request_discussions(self, project: str, repository: str,
                                            review_id: str) -> list[dict[str, Any]]:
        """Get all discussions, comments, and timeline messages on a merge request.

        Returns both code discussions (with file/line context) and general timeline
        messages (including bot messages like Patronus dry run results).

        Args:
            project: Project key
            repository: Repository name
            review_id: Review identifier

        Returns:
            List of items, each with a "type" field:
            - "code_discussion": has file, line, resolved, comments
            - "message": has text, author, created
        """
        # First get the code review to get the feed channel ID
        id_prefix = "number" if review_id.isdigit() else "id"
        review_url = f"{self.base_url}/api/http/projects/key:{project}/code-reviews/{id_prefix}:{review_id}"

        async with httpx.AsyncClient() as client:
            # Get review with feedChannel
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

            # Get feed messages — include author details and time for general messages
            messages_url = f"{self.base_url}/api/http/chats/messages"
            params = {
                "channel": f"id:{channel_id}",
                "sorting": "FromOldestToNewest",
                "batchSize": "50",
                "$fields": "messages(id,text,author(name,details(user(username,name))),time,details(codeDiscussion(id,resolved,channel(id),anchor(filename,line))))",
            }

            response = await client.get(messages_url, headers=self._headers(), params=params)
            response.raise_for_status()
            feed_data = response.json()

            results: list[dict[str, Any]] = []
            for msg in feed_data.get("messages", []):
                details = msg.get("details") or {}
                code_disc = details.get("codeDiscussion")

                if code_disc:
                    # Code discussion — fetch the comment thread
                    disc_channel_id = (code_disc.get("channel") or {}).get("id")
                    anchor = code_disc.get("anchor") or {}

                    thread_messages = []
                    if disc_channel_id:
                        thread_params = {
                            "channel": f"id:{disc_channel_id}",
                            "sorting": "FromOldestToNewest",
                            "batchSize": "50",
                            "$fields": "messages(id,text,author(name,details(user(username,name))),time)",
                        }
                        thread_response = await client.get(
                            messages_url, headers=self._headers(), params=thread_params
                        )
                        if thread_response.status_code == 200:
                            thread_data = thread_response.json()
                            for thread_msg in thread_data.get("messages", []):
                                text = thread_msg.get("text")
                                if not text:
                                    continue
                                thread_messages.append({
                                    "text": text,
                                    "author": _extract_author(thread_msg),
                                    "created": thread_msg.get("time"),
                                })

                    results.append({
                        "type": "code_discussion",
                        "id": code_disc.get("id"),
                        "file": anchor.get("filename"),
                        "line": anchor.get("line"),
                        "resolved": code_disc.get("resolved", False),
                        "comments": thread_messages,
                    })
                else:
                    # General timeline message (bot messages, status changes, etc.)
                    text = msg.get("text")
                    if not text:
                        continue
                    results.append({
                        "type": "message",
                        "text": text,
                        "author": _extract_author(msg),
                        "created": msg.get("time"),
                    })

            return results

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
