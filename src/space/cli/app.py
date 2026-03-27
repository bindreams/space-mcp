"""Space CLI application and shared infrastructure."""

from __future__ import annotations

import asyncio
import functools
import sys
from typing import Any

import click

from ..client import SpaceClient
from ..auth import resolve_token
from ..context import GitContext, resolve_context
from ..models import MergeRequest
from ..patronus import PatronusClient

# Async click adapter ==================================================================================================


def async_command(f):
    """Decorator to run async click commands with asyncio.run()."""

    @functools.wraps(f)
    def wrapper(*args, **kwargs):

        async def _with_cleanup():
            try:
                return await f(*args, **kwargs)
            finally:
                ctx = click.get_current_context(silent=True)
                if ctx is not None and isinstance(ctx.obj, CliState):
                    await ctx.obj.aclose()

        return asyncio.run(_with_cleanup())

    return wrapper


# Shared state passed through click context ============================================================================


class CliState:
    """Shared CLI state, attached to click context."""

    def __init__(self, project: str | None, repo: str | None, json_fields: str | None):
        self._project = project
        self._repo = repo
        self.json_fields = json_fields
        self._context: GitContext | None = None
        self._space_client: SpaceClient | None = None
        self._patronus_client: PatronusClient | None = None

    @property
    def context(self) -> GitContext:
        if self._context is None:
            self._context = resolve_context(project=self._project, repo=self._repo)
        return self._context

    @property
    def use_json(self) -> bool:
        return self.json_fields is not None

    def require_project(self) -> str:
        project = self.context.project
        if not project:
            raise click.UsageError(
                "Could not determine project. Use -P/--project or set SPACE_PROJECT, "
                "or run from a git repo with a JetBrains Space remote."
            )
        return project

    def require_repo(self) -> str:
        repo = self.context.repo
        if not repo:
            raise click.UsageError(
                "Could not determine repository. Use -R/--repo or set SPACE_REPO, "
                "or run from a git repo with a JetBrains Space remote."
            )
        return repo

    def require_token(self) -> str:
        token = resolve_token()
        if not token:
            raise click.UsageError("Authentication required. Set SPACE_TOKEN or run `space auth login`.")
        return token

    def space_client(self) -> SpaceClient:
        if self._space_client is None:
            self._space_client = SpaceClient(self.require_token())
        return self._space_client

    def patronus_client(self) -> PatronusClient:
        if self._patronus_client is None:
            self._patronus_client = PatronusClient(
                self.require_token(),
                space_client=self.space_client(),
            )
        return self._patronus_client

    async def aclose(self) -> None:
        if self._patronus_client is not None:
            await self._patronus_client.aclose()
        if self._space_client is not None:
            await self._space_client.aclose()


pass_state = click.make_pass_decorator(CliState)

# MR argument resolution ===============================================================================================


def parse_mr_ref(ref: str | None) -> dict[str, str | None]:
    """Parse an MR reference (number, URL, or branch name).

    Returns dict with keys: number, branch, project, repo.
    Only one of number/branch will be set.
    """
    if ref is None:
        return {"number": None, "branch": None, "project": None, "repo": None}
    if ref.isdigit():
        return {"number": ref, "branch": None, "project": None, "repo": None}
    # URL: https://jetbrains.team/p/<project>/reviews/<number>/...
    if "jetbrains.team" in ref:
        import re
        m = re.search(r"/p/([^/]+)/reviews/(\d+)", ref)
        if m:
            return {"number": m.group(2), "branch": None, "project": m.group(1), "repo": None}
    # Otherwise treat as branch name
    return {"number": None, "branch": ref, "project": None, "repo": None}


async def resolve_mr(state: CliState, mr_ref: str | None) -> MergeRequest:
    """Resolve an MR reference to a MergeRequest.

    Handles: number, URL, branch name, or None (current branch).
    """
    parsed = parse_mr_ref(mr_ref)
    project = parsed["project"] or state.require_project()
    repo = state.require_repo()
    client = state.space_client()

    if parsed["number"]:
        return await client.get_merge_request(project, repo, parsed["number"])

    # Resolve by branch name (explicit or current)
    branch = parsed["branch"] or state.context.branch
    if not branch:
        raise click.UsageError(
            "No merge request specified and could not detect current branch. "
            "Pass a MR number, URL, or branch name."
        )
    mr = await client.find_merge_request_by_branch(project, repo, branch)
    if mr is None:
        raise click.ClickException(f"No merge request found for branch '{branch}'.")
    return mr
