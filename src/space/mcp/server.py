from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import textwrap
from typing import Any

import httpx

from ..auth import resolve_token
from ..client import SpaceClient, MergeRequestEditError
from ..transport import ApiTimeoutError
from ..models import (
    AttemptStatus,
    CheckStatus,
    MergeRequest,
    MRStateFilter,
    ReviewRef,
    RunStatus,
    SafeMergeStart,
    TimelineMessage,
)
from ..aio import gather_all, gather_cancelling
from ..patronus import PatronusClient, fetch_checks_for_running, fetch_or_drop, no_review_number_message
from ..formatting import describe_error as _describe, human_size
from ..config import ConfigError
from ..models.enums import UnrecognisedApiValue
from ..mutation import MutationCompletedError
from ..strict import InvalidStrictSetting, StrictSetting, apply_strict
from .base import MCP, mcptool
from .hints import mutation_hint, strict_sentence
from .format import (
    format_merge_request,
    format_create_result,
    format_discussions,
    format_merge_request_list,
    format_patronus_runs,
    format_patronus_run_details,
)

_logger = logging.getLogger(__name__)

_AUTH_ERROR_MSG = (
    "**Authentication required.** Set the `SPACE_TOKEN` environment variable "
    "or run `space auth login` to store credentials."
)

_DRY_RUN_CHECK_HINT = (
    "Use `get_patronus_runs` with the project and review ID to check the "
    "status of existing runs. Use `post_cancel_patronus_run` to cancel a stuck "
    "run before retrying."
)

_DEFAULT_LIMIT_NOTE = textwrap.dedent(
    """\
    ---
    Note: `limit` defaults to 1. Set `limit=0` to find all merge requests matching criteria.
"""
)

# Helpers ==============================================================================================================

# Declaration order for the message; the frozenset for membership. `str in MRStateFilter` raises on 3.11.
_STATE_FILTERS = tuple(m.value for m in MRStateFilter if m is not MRStateFilter.UNKNOWN)
_STATE_FILTER_VALUES = frozenset(_STATE_FILTERS)

_SETTLED_STATUSES = frozenset({RunStatus.SUCCESS, RunStatus.FAILURE, RunStatus.CANCELED})

# Transient transport faults: the follow-up check failing this way says nothing about the check itself.
_TRANSIENT = (httpx.TransportError, )


def _sentence(text: str) -> str:
    return text if text.endswith(("?", "!")) else f"{text}."


# Follow-up notes ------------------------------------------------------------------------------------------------------


def _followup_unconfirmed() -> str:
    return f"Note: the dry run may have started despite this error. {_DRY_RUN_CHECK_HINT}"


def _strict_part(exc: Exception, strict_hint: str) -> str:
    return f"{strict_hint} " if isinstance(exc, UnrecognisedApiValue) else ""


def _followup_check_failed(exc: Exception, strict_hint: str) -> str:
    return (
        f"Note: the dry run may have started despite this error, but checking failed: {_sentence(_describe(exc))} "
        f"{_strict_part(exc, strict_hint)}{_DRY_RUN_CHECK_HINT}"
    )


def _followup_unknown_status(run_id: str, status: RunStatus) -> str:
    return (
        f"However, a dry run exists for this merge request "
        f"(run `{run_id}`, status: {status.value}). "
        f"Use `get_patronus_run` with run ID `{run_id}` to inspect it before starting another."
    )


def _followup_in_progress(run_id: str, status: RunStatus) -> str:
    state = "is being cancelled" if status == RunStatus.CANCELING else "is running"
    return (
        f"However, a dry run **{state}** for this merge request "
        f"(run `{run_id}`, status: {status.value}). "
        f"Use `get_patronus_run` with run ID `{run_id}` to track progress."
    )


def _followup_read_failed(run_id: str, exc: Exception, strict_hint: str) -> str:
    return (
        f"However, a dry run may exist for this merge request (run `{run_id}`), "
        f"but its status could not be read: {_sentence(_describe(exc))} {_strict_part(exc, strict_hint)}"
        f"Use `get_patronus_run` with run ID `{run_id}` to inspect it before starting another."
    )


async def _check_dry_run_started(
    space_client: SpaceClient,
    patronus_client: PatronusClient,
    project: str,
    ref: ReviewRef,
    *,
    strict_hint: str,
) -> str:
    """Report whether a dry run exists for the given MR despite an error.

    `strict_hint` follows the error text when the check failed on a strict-mode rejection.

    Always returns the note to append to the original error. Never raises `Exception` (except `AssertionError`,
    which marks a contract violation); cancellation and interrupts propagate.
    """
    from ..patronus import extract_run_ids

    run_id = None
    try:
        items = await space_client.get_merge_request_discussions(project, "", ref)
        text = "\n".join(item.text for item in items if isinstance(item, TimelineMessage))
        run_ids = extract_run_ids(text)
        if not run_ids:
            _logger.debug("Dry run follow-up for review %s: no run ID in the timeline", ref)
            return _followup_unconfirmed()
        run_id = run_ids[-1]
        run = await patronus_client.get_run(run_id)
        if run.status in _SETTLED_STATUSES:
            _logger.debug("Dry run follow-up for review %s: last run %s is settled (%s)", ref, run_id, run.status.value)
            return _followup_unconfirmed()  # the last run in the timeline is probably an older, settled one
        if run.status is RunStatus.UNKNOWN:
            return _followup_unknown_status(run_id, run.status)
        return _followup_in_progress(run_id, run.status)
    except AssertionError as exc:
        if run_id is not None:  # the run ID would otherwise be lost with the swallowed result
            exc.add_note(f"dry-run follow-up: run {run_id} exists for this merge request")
            _logger.debug(
                "Dry run follow-up for review %s: assertion failed after finding run %s", ref, run_id, exc_info=True
            )
        raise
    except Exception as exc:
        transient = isinstance(exc, _TRANSIENT)
        _logger.debug("Dry run follow-up for review %s (run %s) failed: %r", ref, run_id, exc, exc_info=not transient)
        if run_id is not None:
            return _followup_read_failed(run_id, exc, strict_hint)
        return _followup_unconfirmed() if transient else _followup_check_failed(exc, strict_hint)


def _format_safe_merge_result(result: SafeMergeStart) -> str:
    """Format a Space safe-merge response into markdown."""
    if result.events is not None:
        errors = [e.message or "" for e in result.events if e.type == "Error"]
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
        progress = [e.message or "" for e in result.events if e.type == "Progress"]
        if progress:
            return "Dry run started.\n\n" + "\n".join(f"- {m}" for m in progress)
        return "Dry run started."

    parts: list[str] = ["Dry run started.\n"]
    if result.job_id is not None:
        parts.append(f"**Job ID:** `{result.job_id}`")
    if result.run_id is not None:
        parts.append(f"**Run ID:** `{result.run_id}`")
    if result.run_url is not None:
        parts.append(f"**Patronus:** {result.run_url}")
    if result.status is not None:
        parts.append(f"**Status:** {result.status}")
    return "\n".join(parts) if len(parts) > 1 else "Dry run started."


# SpaceMCP =============================================================================================================


class SpaceMCP(MCP):

    def __init__(self, token: str | None = None, *, strict: StrictSetting | None = None) -> None:
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
        self._strict = strict

    @property
    def token(self) -> str | None:
        return self._token

    @token.setter
    def token(self, value: str | None) -> None:
        self._token = value
        self.space_client = SpaceClient(value)
        self.patronus_client = PatronusClient(value, space_client=self.space_client)

    async def __aenter__(self) -> SpaceMCP:
        try:
            await gather_cancelling(self.space_client.warmup(), self.patronus_client.warmup())
        except BaseException:
            await self.__aexit__()  # __aexit__ never runs when entering fails
            raise
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.patronus_client.aclose()
        await self.space_client.aclose()

    def format_error(self, exc: Exception) -> str:
        if isinstance(exc, UnrecognisedApiValue):
            return f"**Error:** {exc}\n\n{strict_sentence(self._strict)}"
        if isinstance(exc, MutationCompletedError):
            hint = mutation_hint(exc, self._strict)
            return f"**Error:** {exc}\n\n{hint}" if hint else f"**Error:** {exc}"
        if isinstance(exc, MergeRequestEditError):
            return f"**Partial edit:** {exc}"
        if isinstance(exc, ApiTimeoutError):
            # The message already names the service (Space API / Patronus), so the
            # prefix stays neutral to avoid mislabeling a Patronus timeout as Space.
            return f"**Timed out:** {exc}"
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
            review_id: MR number (e.g., "194108"), or "id:<internal id>" for an internal ID.
                A bare all-digit value is always read as a number.

        Returns:
            YAML with MR title, state, author, branches, and reviewers.
        """
        result = await self.space_client.get_merge_request(project, repository, ReviewRef.parse(review_id))
        return format_merge_request(result)

    @mcptool(name="get_merge_request_timeline", title="Get Merge Request Timeline")
    async def get_merge_request_timeline(self, project: str, repository: str, review_id: str) -> str:
        """Get the full timeline of a merge request: comments, dry runs, commits, reviews.

        Returns a chronological markdown timeline with day sections, threaded replies
        (Patronus dry run results, safe merge status), and code review discussions.

        Args:
            project: Project key (e.g., "ij")
            repository: Repository name (e.g., "ultimate")
            review_id: MR number (e.g., "194108"), or "id:<internal id>" for an internal ID.
                A bare all-digit value is always read as a number.

        Returns:
            Markdown timeline grouped by day, with threaded replies indented.
        """
        result = await self.space_client.get_merge_request_discussions(project, repository, ReviewRef.parse(review_id))
        return format_discussions(result)

    @mcptool(name="get_merge_requests", title="Find Merge Requests")
    async def get_merge_requests(
        self,
        project: str,
        repository: str,
        branch: str | None = None,
        state: str | None = None,
        limit: int | None = None,
        author: str | None = None,
    ) -> str:
        """List merge requests for a repository.

        Args:
            project: Project key (e.g., "ij")
            repository: Repository name (e.g., "ultimate")
            branch: Optional source branch name to filter by
            state: Optional state filter: "Opened", "Closed", "Merged",
                "RequiresAuthorAttention", or "NeedsReview"
            limit: Maximum number of results (default 1; set to 0 for unlimited)
            author: Optional author username to filter by (case-insensitive; an unknown
                username yields a clear "no such user" error)

        Returns:
            YAML list of merge requests.
        """
        limit_was_defaulted = limit is None
        if limit is None:
            effective_limit = 1
        elif limit < 0:
            return "**Error:** limit must be >= 0."
        elif limit == 0:
            effective_limit = None  # unlimited
        else:
            effective_limit = limit

        if state and state not in _STATE_FILTER_VALUES:
            raise ValueError(f"invalid state {state!r}: expected one of {', '.join(_STATE_FILTERS)}")
        state_filter = MRStateFilter(state) if state else None

        result: list[MergeRequest] = []
        async for mr in self.space_client.list_merge_requests(
            project=project,
            repository=repository,
            branch=branch,
            state=state_filter,
            author=author,
        ):
            result.append(mr)
            if effective_limit is not None and len(result) >= effective_limit:
                break

        output = format_merge_request_list(result)
        if limit_was_defaulted:
            output += _DEFAULT_LIMIT_NOTE
        return output

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

    @mcptool(name="patch_merge_request", title="Edit Merge Request")
    async def patch_merge_request(
        self,
        project: str,
        review_id: str,
        title: str | None = None,
        description: str | None = None,
    ) -> str:
        """Edit an existing merge request's title and/or description.

        Omit a field to leave it unchanged; pass "" for `description` to clear it.
        At least one of `title`/`description` is required.

        Args:
            review_id: MR number (e.g., "194108"), or "id:<internal id>" for an internal ID.
                A bare all-digit value is always read as a number.
            title: New title, or omit to leave unchanged.
            description: New description ("" clears it), or omit to leave unchanged.

        Returns:
            YAML with the updated merge request.
        """
        updated = await self.space_client.edit_merge_request(
            project=project,
            ref=ReviewRef.parse(review_id),
            title=title,
            description=description,
        )
        return format_merge_request(updated)

    @mcptool(name="post_close_merge_request", title="Close Merge Request")
    async def post_close_merge_request(self, project: str, review_id: str) -> str:
        """Close a merge request.

        Args:
            project: Project key (e.g., "ij")
            review_id: MR number (e.g., "194108"), or "id:<internal id>" for an internal ID.
                A bare all-digit value is always read as a number.

        Returns:
            Confirmation message.
        """
        await self.space_client.set_merge_request_state(project, ReviewRef.parse(review_id), "Closed")
        return f"Merge request `{review_id}` closed."

    @mcptool(name="post_reopen_merge_request", title="Reopen Merge Request")
    async def post_reopen_merge_request(self, project: str, review_id: str) -> str:
        """Reopen a closed merge request.

        The source branch must still exist. If it was deleted on close,
        re-push it before reopening.

        Args:
            project: Project key (e.g., "ij")
            review_id: MR number (e.g., "194108"), or "id:<internal id>" for an internal ID.
                A bare all-digit value is always read as a number.

        Returns:
            Confirmation message.
        """
        await self.space_client.set_merge_request_state(project, ReviewRef.parse(review_id), "Opened")
        return f"Merge request `{review_id}` reopened."

    # Comment / discussion tools =======================================================================================

    @mcptool(name="post_merge_request_comment", title="Comment on Merge Request")
    async def post_merge_request_comment(self, project: str, review_id: str, text: str) -> str:
        """Post a general comment on a merge request.

        Args:
            project: Project key (e.g., "ij")
            review_id: MR number (e.g., "194108"), or "id:<internal id>" for an internal ID.
                A bare all-digit value is always read as a number.
            text: Comment text (Markdown supported)

        Returns:
            Confirmation message.
        """
        await self.space_client.post_comment(project, ReviewRef.parse(review_id), text)
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
            review_id: MR number (e.g., "194108"), or "id:<internal id>" for an internal ID.
                A bare all-digit value is always read as a number.
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
            ReviewRef.parse(review_id),
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
            review_id: MR number (e.g., "194108"), or "id:<internal id>" for an internal ID.
                A bare all-digit value is always read as a number.

        Returns:
            Confirmation message.
        """
        await self.space_client.set_merge_request_state(project, ReviewRef.parse(review_id), "Deleted")
        return f"Merge request `{review_id}` deleted."

    # Patronus tools ===================================================================================================

    @mcptool(name="get_patronus_runs", title="List Patronus Runs")
    async def get_patronus_runs(self, project: str, review_id: str) -> str:
        """Find Patronus runs (dry runs / safe merges) for a merge request.

        Use this to discover CI dry runs and safe merge attempts for a merge request.
        Each run has an ID that can be passed to get_patronus_run.

        Args:
            project: Project key (e.g., "ij")
            review_id: MR number (e.g., "194108"), or "id:<internal id>" for an internal ID.
                A bare all-digit value is always read as a number.

        Returns:
            YAML list of runs with IDs for follow-up queries.
        """
        ref = ReviewRef.parse(review_id)
        mr = await self.space_client.get_merge_request(project, "", ref)
        if not mr.branch_pair:
            return "No branch pair found on this merge request — cannot look up Patronus runs."
        source = mr.branch_pair.source_branch
        target = mr.branch_pair.target_branch
        if ref.number is None:  # id input: use the number Space reports
            ref = ReviewRef.for_mr(mr)
            if ref.number is None:
                return no_review_number_message(ref)

        result = await self.patronus_client.list_runs_for_review(
            project,
            ref.number,
            source_branch=source,
            target_branch=target,
        )
        commits: dict[str, str | None] = {}
        changes_list = await gather_all(
            fetch_or_drop(self.patronus_client.get_run_changes(r.id), what="commit", run_id=r.id) for r in result
        )
        for r, ch in zip(result, changes_list, strict=True):
            commits[r.id] = ch[-1].get("hash", "")[:8] if ch else None

        checks_by_run = await fetch_checks_for_running(self.patronus_client, result)
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
            if check.status != CheckStatus.FAILURE:
                continue
            failed = [a for a in check.attempts if a.status == AttemptStatus.FAILURE]
            if not failed:
                continue
            attempt = failed[-1]
            if not attempt.id:
                continue
            try:
                details = await self.patronus_client.get_attempt_details(attempt.id)
                attempt_details[check.config.name] = details
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as exc:
                # best-effort: omit details if Patronus is unreachable
                _logger.debug("Omitting attempt details for check %s: %r", check.config.name, exc, exc_info=exc)

        return format_patronus_run_details(
            run, tc_checks, problems, attempt_details, patronus_base_url=self.patronus_client.base_url
        )

    @mcptool(name="put_patronus_dry_run", title="Start Patronus Dry Run")
    async def put_patronus_dry_run(self, project: str, review_id: str) -> str:
        """Start a Patronus dry run for a merge request.

        Runs all configured quality checks (TeamCity builds) without merging.
        Use get_patronus_run to track progress.

        Args:
            project: Project key (e.g., "ij")
            review_id: MR number (e.g., "194108"), or "id:<internal id>" for an internal ID.
                A bare all-digit value is always read as a number.

        Returns:
            Markdown with run ID, Patronus URL, and status.
            On failure, returns actionable guidance on what to do next.
        """
        # Resolve first so a failure precedes the POST.
        ref = ReviewRef.parse(review_id)
        merge_target: ReviewRef | MergeRequest = (
            ref if ref.id is not None else await self.space_client.get_merge_request(project, "", ref)
        )
        # From here on the POST may have been answered, so every failure gets the follow-up.
        try:
            result = await self.space_client.start_safe_merge(project, merge_target, operation="DryRun")
            return _format_safe_merge_result(result)
        except AssertionError:
            raise
        except Exception as exc:
            return await self._with_dry_run_followup(exc, project, ref)

    async def _with_dry_run_followup(self, exc: Exception, project: str, ref: ReviewRef) -> str:
        _logger.debug("Dry run start for review %s failed: %r", ref, exc, exc_info=True)
        try:
            msg = self.format_error(exc)
        except AssertionError:
            raise
        except Exception:  # rendering must not cost the follow-up
            _logger.debug("Dry run start failure for review %s could not be rendered", ref, exc_info=True)
            msg = f"**Error:** {type(exc).__name__}"
        followup = await _check_dry_run_started(
            self.space_client, self.patronus_client, project, ref, strict_hint=strict_sentence(self._strict)
        )
        return f"{msg}\n\n{followup}"

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


async def amain(setting: StrictSetting | None = None) -> None:
    """Run the MCP server with stdio transport."""
    async with SpaceMCP(resolve_token(), strict=setting) as server:
        await server.run_stdio_async()


def main() -> None:
    """Resolve strict mode, then serve; a bad setting exits 2 before the server starts."""
    try:
        setting = apply_strict(None, os.environ)
    except (ConfigError, InvalidStrictSetting) as exc:
        print(f"space-mcp: {(str(exc).splitlines() or [type(exc).__name__])[0]}", file=sys.stderr)
        raise SystemExit(2) from exc
    asyncio.run(amain(setting))


if __name__ == "__main__":
    sys.exit(main())
