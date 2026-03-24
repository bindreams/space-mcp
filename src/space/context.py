"""Git context inference for the Space CLI and MCP server.

Detects project, repository, and branch from git remote URLs and HEAD.
"""

import os
import re
import subprocess
from dataclasses import dataclass

SPACE_URL = "https://jetbrains.team"

# Remote URL patterns for JetBrains Space git =================================
_REMOTE_PATTERNS = [
    # https://git.jetbrains.team/<project>/<repo>.git
    re.compile(r"https?://git\.jetbrains\.team/(?P<project>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$"),
    # ssh://git@git.jetbrains.team/<project>/<repo>
    re.compile(r"ssh://git@git\.jetbrains\.team/(?P<project>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$"),
    # git@git.jetbrains.team:<project>/<repo>.git
    re.compile(r"git@git\.jetbrains\.team:(?P<project>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$"),
]


@dataclass
class GitContext:
    project: str | None = None
    repo: str | None = None
    branch: str | None = None


def _run_git(*args: str) -> str | None:
    """Run a git command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _parse_remote_url(url: str) -> tuple[str, str] | None:
    """Extract (project, repo) from a Space git remote URL."""
    for pattern in _REMOTE_PATTERNS:
        m = pattern.match(url)
        if m:
            return m.group("project"), m.group("repo")
    return None


def detect_git_context() -> GitContext:
    """Detect project, repo, and branch from the current git repository."""
    ctx = GitContext()

    # Branch -----
    branch = _run_git("symbolic-ref", "--short", "HEAD")
    if branch:
        ctx.branch = branch

    # Remote URL → project + repo -----
    remote_url = _run_git("remote", "get-url", "origin")
    if remote_url:
        parsed = _parse_remote_url(remote_url)
        if parsed:
            ctx.project, ctx.repo = parsed

    return ctx


def resolve_context(
    project: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> GitContext:
    """Resolve context from explicit args > env vars > git inference.

    Priority (highest first):
    1. Explicit arguments (from CLI flags)
    2. Environment variables (SPACE_PROJECT, SPACE_REPO)
    3. Git repository inference
    """
    git_ctx = detect_git_context()
    return GitContext(
        project=project or os.environ.get("SPACE_PROJECT") or git_ctx.project,
        repo=repo or os.environ.get("SPACE_REPO") or git_ctx.repo,
        branch=branch or git_ctx.branch,
    )
