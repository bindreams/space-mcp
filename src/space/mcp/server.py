from __future__ import annotations

import asyncio
import re

import httpx

from ..auth import resolve_token
from ..client import SpaceClient
from ..models import RunStatus, TimelineMessage
from ..patronus import PatronusClient, fetch_checks_for_active
from ..formatting import human_size
from .base import MCP, mcptool
from .format import (
    format_merge_request,
    format_create_result,
    format_discussions,
    format_merge_request_list,
    format_patronus_runs,
    format_patronus_run_details,
)

_AUTH_ERROR_MSG = (
    "**Authentication required.** Set the `SPACE_TOKEN` environment variable "
    "or run `space auth login` to store credentials."
)

_DRY_RUN_CHECK_HINT = (
    "Use `get_patronus_runs` with the project and review ID to check the "
    "status of existing runs. Use `post_cancel_patronus_run` to cancel a stuck "
    "run before retrying."
)


# Helpers ==============================================================================================================
async def _check_dry_run_started(
    space_client: SpaceClient,
    patronus_client: PatronusClient,
    project: str,
    review_id: str,
) -> str | None:
    """Check if a dry run exists for the given MR despite an error."""
    from ..patronus import extract_run_ids

    try:
        items = await space_client.get_merge_request_discussions(project, "", review_id)
        text = "\n".join(item.text for item in items if isinstance(item, TimelineMessage))
        run_ids = extract_run_ids(text)
        if not run_ids:
            return None
        run_id = run_ids[-1]
        run = await patronus_client.get_run(run_id)
        status = run.status.value
        return (
            f"However, a dry run **is running** for this merge request "
            f"(run `{run_id}`, status: {status}). "
            f"Use `get_patronus_run` with run ID `{run_id}` to track progress."
        )
    except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException, KeyError):
        return None  # best-effort followup check


def _format_safe_merge_result(result: dict | list) -> str:
    """Format a Space safe-merge response into markdown."""
    if isinstance(result, list):
        errors = [e["message"] for e in result if e.get("type") == "Error"]
        if errors:
            joined = "; ".join(errors)
            if "already exists" in joined:
                return (
                    "**Dry run not started:** a dry run or merge is already "
                    "in progress for this merge request.\n\n" + _DRY_RUN_CHECK_HINT
                )
            if "secret" in joined.lower() and "not found" in joined.lower():
                secret_match = re.search(r"\$\{([^}]+)\}", joined)
                secret_name = secret_match.group(1) if secret_match else "safe.merge.patronus.starter.space.token"
                return (
                    f"**Dry run not started:** the project secret `{secret_name}` "
                    f"is not configured.\n\n"
                    f"To fix this, add the secret in Space project parameters:\n"
                    f"1. Ask the Patronus application owner to issue a permanent token "
                    f"from the Space Safe-Merge → Patronus Starter application\n"
                    f"2. Add it as a secret named `{secret_name}` in the project parameters"
                )
            if "not defined" in joined.lower() and "quality gate" in joined.lower():
                return (
                    "**Dry run not started:** safe merge is not configured for this repository.\n\n"
                    "To fix this:\n"
                    "1. Enable Quality Gates in the branch protection rules for the target branch\n"
                    "2. Enable Safe Merge and link a `.space/safe-merge.yaml` configuration file\n"
                    "3. The config file must be committed to the protected branch"
                )
            return f"**Dry run failed:** {joined}"
        progress = [e["message"] for e in result if e.get("type") == "Progress"]
        if progress:
            return "Dry run started.\n\n" + "\n".join(f"- {m}" for m in progress)
        return "Dry run started."

    parts: list[str] = ["Dry run started.\n"]
    if "jobId" in result:
        parts.append(f"**Job ID:** `{result['jobId']}`")
    if "robotId" in result:
        parts.append(f"**Run ID:** `{result['robotId']}`")
    if "robotUrl" in result:
        parts.append(f"**Patronus:** {result['robotUrl']}")
    if "status" in result:
        parts.append(f"**Status:** {result['status']}")
    return "\n".join(parts) if len(parts) > 1 else "Dry run started."


# SpaceMCP =============================================================================================================


class SpaceMCP(MCP):

    def __init__(self, token: str | None = None) -> None:
        super().__init__(
            name="space",
            instructions=(
                "JetBrains Space merge-request and Patronus CI tools.\n\n"
                "Tool categories:\n"
                "- Merge requests: get, list, create, close, reopen, delete\n"
                "- Comments & discussions: post comments, create/reply to code discussions\n"
                "- Patronus CI: list runs, inspect run details, start dry runs, cancel runs\n"
                "- Attachments: download files from MR discussions"
            ),
        )
        self.token = token

    @property
    def token(self) -> str | None:
        return self._token

    @token.setter
    def token(self, value: str | None) -> None:
        self._token = value
        self.space_client = SpaceClient(value)
        self.patronus_client = PatronusClient(value, space_client=self.space_client)

    def format_error(self, exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status in (401, 403) and self._token is None:
                return _AUTH_ERROR_MSG
            detail = exc.response.text or exc.response.reason_phrase or str(exc) or f"HTTP {status}"
            return f"**Space API error ({status}):** {detail}"
        return super().format_error(exc)

    # Merge request tools ==============================================================================================

    @mcptool(name="get_merge_request", title="Get Merge Request")
    async def get_merge_request(self, project: str, repository: str, review_id: str) -> str:
        """Get details of a specific merge request.

        Args:
            project: Project key (e.g., "ij" for IntelliJ)
            repository: Repository name (e.g., "ultimate")
            review_id: Review/MR identifier (numeric ID or full review ID)

        Returns:
            YAML with MR title, state, author, branches, and reviewers.
        """
        result = await self.space_client.get_merge_request(project, repository, review_id)
        return format_merge_request(result)

    @mcptool(name="get_merge_request_timeline", title="Get Merge Request Timeline")
    async def get_merge_request_timeline(self, project: str, repository: str, review_id: str) -> str:
        """Get the full timeline of a merge request: comments, dry runs, commits, reviews.

        Returns a chronological markdown timeline with day sections, threaded replies
        (Patronus dry run results, safe merge status), and code review discussions.

        Args:
            project: Project key (e.g., "ij")
            repository: Repository name (e.g., "ultimate")
            review_id: Review/MR identifier

        Returns:
            Markdown timeline grouped by day, with threaded replies indented.
        """
        result = await self.space_client.get_merge_request_discussions(project, repository, review_id)
        return format_discussions(result)

    @mcptool(name="get_merge_requests", title="Find Merge Requests")
    async def get_merge_requests(
        self,
        project: str,
        repository: str,
        branch: str | None = None,
        state: str | None = None,
        limit: int = 20,
        author: str | None = None,
    ) -> str:
        """List merge requests for a repository.

        Args:
            project: Project key (e.g., "ij")
            repository: Repository name (e.g., "ultimate")
            branch: Optional source branch name to filter by
            state: Optional state filter: "Open", "Closed", or "Merged"
            limit: Maximum number of results (default 20)
            author: Optional author username to filter by (case-insensitive)

        Returns:
            YAML list of merge requests.
        """
        result = await self.space_client.list_merge_requests(
            project=project,
            repository=repository,
            branch=branch,
            state=state,
            limit=limit,
            author=author,
        )
        return format_merge_request_list(result)

    @mcptool(name="put_merge_request", title="Create Merge Request")
    async def put_merge_request(
        self,
        project: str,
        repository: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str | None = None,
    ) -> str:
        """Create a new merge request.

        Args:
            project: Project key (e.g., "ij")
            repository: Repository name (e.g., "ultimate")
            source_branch: Branch with changes (e.g., "azhukova/fix-auth")
            target_branch: Branch to merge into (e.g., "master")
            title: MR title
            description: Optional MR description

        Returns:
            YAML with created MR number, title, and branches.
        """
        result = await self.space_client.create_merge_request(
            project=project,
            repository=repository,
            source_branch=source_branch,
            target_branch=target_branch,
            title=title,
            description=description,
        )
        return format_create_result(result)

    @mcptool(name="post_close_merge_request", title="Close Merge Request")
    async def post_close_merge_request(self, project: str, review_id: str) -> str:
        """Close a merge request.

        Args:
            project: Project key (e.g., "ij")
            review_id: MR number (e.g., "194108") or internal ID

        Returns:
            Confirmation message.
        """
        await self.space_client.set_merge_request_state(project, review_id, "Closed")
        return f"Merge request `{review_id}` closed."

    @mcptool(name="post_reopen_merge_request", title="Reopen Merge Request")
    async def post_reopen_merge_request(self, project: str, review_id: str) -> str:
        """Reopen a closed merge request.

        The source branch must still exist. If it was deleted on close,
        re-push it before reopening.

        Args:
            project: Project key (e.g., "ij")
            review_id: MR number (e.g., "194108") or internal ID

        Returns:
            Confirmation message.
        """
        await self.space_client.set_merge_request_state(project, review_id, "Opened")
        return f"Merge request `{review_id}` reopened."

    # Comment / discussion tools =======================================================================================

    @mcptool(name="post_merge_request_comment", title="Comment on Merge Request")
    async def post_merge_request_comment(self, project: str, review_id: str, text: str) -> str:
        """Post a general comment on a merge request.

        Args:
            project: Project key (e.g., "ij")
            review_id: MR number (e.g., "194108") or internal ID
            text: Comment text (Markdown supported)

        Returns:
            Confirmation message.
        """
        await self.space_client.post_comment(project, review_id, text)
        return f"Comment posted on MR `{review_id}`."

    @mcptool(name="post_code_discussion", title="Create Code Discussion")
    async def post_code_discussion(
        self,
        project: str,
        review_id: str,
        repository: str,
        revision: str,
        filename: str,
        line: int,
        text: str,
    ) -> str:
        """Create an inline code discussion on a specific file and line of a merge request.

        Args:
            project: Project key (e.g., "ij")
            review_id: MR number (e.g., "194108") or internal ID
            repository: Repository name (e.g., "ultimate")
            revision: Git commit SHA the comment is anchored to
            filename: File path (e.g., "src/main.py")
            line: Line number (new side of the diff)
            text: Comment text (Markdown supported)

        Returns:
            Confirmation with file and line reference.
        """
        await self.space_client.create_code_discussion(
            project,
            review_id,
            repository,
            revision,
            filename,
            line,
            text,
        )
        return f"Code discussion created on `{filename}:{line}`."

    @mcptool(name="post_reply_to_code_discussion", title="Reply to Code Discussion")
    async def post_reply_to_code_discussion(
        self,
        project: str,
        review_id: str,
        discussion_channel_id: str,
        text: str,
    ) -> str:
        """Reply to an existing code discussion on a merge request.

        The discussion_channel_id can be found in the timeline output of a merge request.

        Args:
            project: Project key (for context only)
            review_id: MR number (for context only)
            discussion_channel_id: Channel ID of the code discussion to reply to
            text: Reply text (Markdown supported)

        Returns:
            Confirmation message.
        """
        await self.space_client.reply_to_discussion(discussion_channel_id, text)
        return "Reply posted."

    @mcptool(name="post_delete_merge_request", title="Delete Merge Request")
    async def post_delete_merge_request(self, project: str, review_id: str) -> str:
        """Delete a merge request.

        Args:
            project: Project key (e.g., "ij")
            review_id: MR number (e.g., "194108") or internal ID

        Returns:
            Confirmation message.
        """
        await self.space_client.set_merge_request_state(project, review_id, "Deleted")
        return f"Merge request `{review_id}` deleted."

    # Patronus tools ===================================================================================================

    @mcptool(name="get_patronus_runs", title="List Patronus Runs")
    async def get_patronus_runs(self, project: str, review_id: str) -> str:
        """Find Patronus runs (dry runs / safe merges) for a merge request.

        Use this to discover CI dry runs and safe merge attempts for a merge request.
        Each run has an ID that can be passed to get_patronus_run.

        Args:
            project: Project key (e.g., "ij")
            review_id: MR number (e.g., "194108")

        Returns:
            YAML list of runs with IDs for follow-up queries.
        """
        mr = await self.space_client.get_merge_request(project, "", review_id)
        if not mr.branch_pair:
            return "No branch pair found on this merge request — cannot look up Patronus runs."
        source = mr.branch_pair.source_branch
        target = mr.branch_pair.target_branch

        result = await self.patronus_client.list_runs_for_review(
            project,
            review_id,
            source_branch=source,
            target_branch=target,
        )
        commits: dict[str, str | None] = {}
        changes_list = await asyncio.gather(
            *(self.patronus_client.get_run_changes(r.id) for r in result),
            return_exceptions=True,
        )
        for r, ch in zip(result, changes_list):
            if isinstance(ch, Exception) or not ch:
                commits[r.id] = None
            else:
                commits[r.id] = ch[-1].get("hash", "")[:8]

        # Fetch checks for active runs to derive effective status
        checks_by_run = await fetch_checks_for_active(self.patronus_client, result)
        # ty doesn't recognize list as a subtype of Sequence in dict values (covariance)
        return format_patronus_runs(result, commits, checks=checks_by_run or None)  # ty: ignore[invalid-argument-type]

    @mcptool(name="get_patronus_run", title="Get Patronus Run")
    async def get_patronus_run(self, run_id: str) -> str:
        """Get details of a specific Patronus run including TeamCity build checks and problems.

        Use the run ID from get_patronus_runs or from a Patronus URL
        (e.g., https://patronus.labs.jb.gg/robot/<run-id>).

        The returned TeamCity build IDs can be inspected further using the teamcity CLI:
            teamcity run view <build-id>

        Args:
            run_id: Patronus run UUID

        Returns:
            YAML with run overview, TeamCity checks, and problems.
        """
        run = await self.patronus_client.get_run(run_id)
        tc_checks = await self.patronus_client.get_run_teamcity_checks(run_id)
        problems = await self.patronus_client.get_run_problems(run_id)

        # Fetch attempt details for failed checks
        from ..models import AttemptDetails
        attempt_details: dict[str, AttemptDetails] = {}
        for check in tc_checks:
            if check.status != RunStatus.FAILURE:
                continue
            failed = [a for a in check.attempts if a.status == RunStatus.FAILURE]
            if not failed:
                continue
            attempt = failed[-1]
            if not attempt.id:
                continue
            try:
                details = await self.patronus_client.get_attempt_details(attempt.id)
                attempt_details[check.config.name] = details
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException):
                pass  # best-effort: omit details if Patronus is unreachable

        return format_patronus_run_details(run, tc_checks, problems, attempt_details)

    @mcptool(name="put_patronus_dry_run", title="Start Patronus Dry Run")
    async def put_patronus_dry_run(self, project: str, review_id: str) -> str:
        """Start a Patronus dry run for a merge request.

        Runs all configured quality checks (TeamCity builds) without merging.
        Use get_patronus_run to track progress.

        Args:
            project: Project key (e.g., "ij")
            review_id: MR number (e.g., "194108")

        Returns:
            Markdown with run ID, Patronus URL, and status.
            On failure, returns actionable guidance on what to do next.
        """
        try:
            result = await self.space_client.start_safe_merge(project, review_id, operation="DryRun")
            return _format_safe_merge_result(result)
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as exc:
            msg = self.format_error(exc)
            followup = await _check_dry_run_started(self.space_client, self.patronus_client, project, review_id)
            if followup:
                return f"{msg}\n\n{followup}"
            return f"{msg}\n\nNote: the dry run may have started despite this error. {_DRY_RUN_CHECK_HINT}"

    @mcptool(name="post_cancel_patronus_run", title="Cancel Patronus Run")
    async def post_cancel_patronus_run(self, run_id: str) -> str:
        """Cancel a running Patronus run (dry run or safe merge).

        Args:
            run_id: Patronus run UUID

        Returns:
            Confirmation message.
        """
        await self.patronus_client.cancel_run(run_id)
        return f"Cancellation requested for run `{run_id}`."

    # Attachment tools =================================================================================================

    @mcptool(name="get_attachment", title="Download Attachment")
    async def get_attachment(self, attachment_id: str) -> str:
        """Download a file attachment from a Space MR discussion.

        Use the attachment ID from get_merge_request_timeline output
        (shown as [id: ...] next to each attachment).

        For text files, returns the file content directly.
        For binary files, returns the download URL.

        Args:
            attachment_id: Attachment UUID

        Returns:
            File content (text) or download URL (binary).
        """
        content, content_type = await self.space_client.download_attachment(attachment_id)

        if content_type and content_type.startswith("text/"):
            return content.decode("utf-8", errors="replace")

        size = human_size(len(content))
        return (f"Binary file ({size}). "
                f"Download: https://jetbrains.team/d/{attachment_id}")


def main():
    """Run the MCP server with stdio transport."""
    SpaceMCP(resolve_token()).run(transport="stdio")


if __name__ == "__main__":
    main()
