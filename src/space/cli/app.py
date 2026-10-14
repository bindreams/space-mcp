"""Space CLI application and shared infrastructure."""

from __future__ import annotations

import asyncio
import functools
import os
import re
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import click

from ..client import SpaceClient
from ..auth import resolve_token
from ..context import GitContext, resolve_context
from ..models import MergeRequest, ReviewRef
from ..config import ConfigError
from ..models.enums import UnrecognisedApiValue
from ..mutation import MutationCompletedError
from ..patronus import PatronusClient
from ..strict import InvalidStrictSetting, apply_strict
from .errors import RERUN_HINT, mutation_click_error

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

        try:
            return asyncio.run(_with_cleanup())
        except MutationCompletedError as err:
            ctx = click.get_current_context(silent=True)
            state = ctx.obj if ctx is not None and isinstance(ctx.obj, CliState) else None
            raise mutation_click_error(err, state) from err
        except UnrecognisedApiValue as exc:
            raise click.ClickException(f"{exc}\n{RERUN_HINT}") from exc

    return wrapper


# Shared state passed through click context ============================================================================


class CliState:
    """Shared CLI state, attached to click context."""

    def __init__(self, project: str | None, repo: str | None, json_fields: str | None, strict: bool | None = None):
        self._project = project
        self._repo = repo
        self.json_fields = json_fields
        self._strict_flag = strict
        self._strict_resolved = False
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

    def _resolve_strict(self) -> None:
        """Resolve strict mode before the first API client exists, so commands without one never read the config."""
        if self._strict_resolved:
            return
        try:
            apply_strict(self._strict_flag, os.environ)
        except (InvalidStrictSetting, ConfigError) as exc:
            raise click.ClickException(str(exc)) from exc
        self._strict_resolved = True

    def space_client(self) -> SpaceClient:
        self._resolve_strict()
        if self._space_client is None:
            self._space_client = SpaceClient(self.require_token())
        return self._space_client

    def patronus_client(self) -> PatronusClient:
        self._resolve_strict()
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


@dataclass(frozen=True)
class ParsedMrRef:
    """A CLI MR argument: a review ref (with its project, for a URL), a branch name, or neither (current branch)."""

    ref: ReviewRef | None = None
    branch: str | None = None
    project: str | None = None


_REVIEW_URL_PATH = re.compile(r"/p/([^/]+)/reviews/([0-9]+)(?:/.*)?")


def parse_mr_ref(ref: str | None) -> ParsedMrRef:
    """Parse an MR argument: number, `id:`/`number:` ref, review URL, or branch name.

    Raises:
        click.BadParameter: the argument is a number or explicit ref that names no merge request (e.g. `0`).
    """
    if not ref:
        return ParsedMrRef()
    try:
        # Git forbids ":" in branch names, so an explicit prefix is never a branch.
        if ref.startswith(("id:", "number:")):
            return ParsedMrRef(ref=ReviewRef.parse(ref))
        review = ReviewRef.parse(ref)
        if review.number is not None:
            return ParsedMrRef(ref=review)
        url = _review_url(ref)
        if url is not None:
            project, number = url
            return ParsedMrRef(ref=ReviewRef.parse(number), project=project)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    return ParsedMrRef(branch=ref)


def _review_url(ref: str) -> tuple[str, str] | None:
    """The (project, number digits) of a Space review URL, matched on its path alone."""
    # urlsplit silently deletes tabs and newlines anywhere, and leading spaces and C0 controls, which would make
    # "…/reviews/12\n" or " https://…/12" read as #12.
    if ref[0] <= " " or any(c in ref for c in "\t\r\n"):
        return None
    try:
        parts = urlsplit(ref if "://" in ref else f"//{ref}")  # "//" makes a scheme-less ref's first segment the host
    except ValueError:  # e.g. a malformed IPv6 host: not a review URL
        return None
    m = _REVIEW_URL_PATH.fullmatch(parts.path) if parts.hostname == "jetbrains.team" else None
    return (m.group(1), m.group(2)) if m else None


async def resolve_mr_with_project(state: CliState, mr_ref: str | None) -> tuple[MergeRequest, str]:
    """Resolve an MR reference to a MergeRequest and the project it was resolved against.

    The returned project is the one used to fetch the MR (from the ref, e.g. a URL,
    else the state project). Actions must PATCH against this project — Space review
    numbers are per-project, so using the state project for a cross-project ref would
    target the wrong MR.

    Handles: number, URL, branch name, or None (current branch).
    """
    parsed = parse_mr_ref(mr_ref)
    project = parsed.project or state.require_project()
    repo = state.require_repo()
    client = state.space_client()

    if parsed.ref is not None:
        return await client.get_merge_request(project, repo, parsed.ref), project

    # Resolve by branch name (explicit or current)
    branch = parsed.branch or state.context.branch
    if not branch:
        raise click.UsageError(
            "No merge request specified and could not detect current branch. "
            "Pass a MR number, URL, or branch name."
        )
    mr = await client.find_merge_request_by_branch(project, repo, branch)
    if mr is None:
        raise click.ClickException(f"No merge request found for branch '{branch}'.")
    return mr, project


async def resolve_mr(state: CliState, mr_ref: str | None) -> MergeRequest:
    """Resolve an MR reference to a MergeRequest.

    Handles: number, URL, branch name, or None (current branch).
    """
    mr, _ = await resolve_mr_with_project(state, mr_ref)
    return mr
