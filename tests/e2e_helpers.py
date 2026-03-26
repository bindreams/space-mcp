"""Git and repo helpers for integration tests.

Provides functions to manage branches and repo state via git subprocess calls,
using a Space PAT for HTTPS authentication.
"""
from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse


def parse_git_url(url: str) -> tuple[str, str]:
    """Extract (project, repo) from a Space git URL.

    >>> parse_git_url("https://git.jetbrains.team/space-mcp/test.git")
    ('space-mcp', 'test')
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/").removesuffix(".git")
    parts = path.split("/")
    if len(parts) != 2:
        raise ValueError(f"Expected https://git.jetbrains.team/<project>/<repo>.git, got: {url}")
    return parts[0], parts[1]


def authenticated_url(repo_url: str, token: str) -> str:
    """Insert PAT into a git HTTPS URL for push access.

    >>> authenticated_url("https://git.jetbrains.team/space-mcp/test.git", "tok")
    'https://:tok@git.jetbrains.team/space-mcp/test.git'
    """
    return repo_url.replace("https://", f"https://:{token}@")


def _redact_token(text: str) -> str:
    """Remove bearer tokens from URLs to avoid leaking secrets in logs."""
    return re.sub(r"https://:[^@]+@", "https://:<REDACTED>@", text)


async def _run_git(*args: str, cwd: str | Path | None = None) -> str:
    """Run a git command and return stdout. Raises on non-zero exit."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        safe_args = _redact_token(" ".join(args))
        safe_stderr = _redact_token(stderr.decode())
        raise RuntimeError(
            f"git {safe_args} failed (rc={proc.returncode}): {safe_stderr}"
        )
    return stdout.decode()


async def list_remote_refs(auth_url: str, pattern: str = "") -> dict[str, str]:
    """List remote refs, optionally filtered by pattern. Returns {ref: sha}."""
    args = ["ls-remote", "--heads", auth_url]
    if pattern:
        args.append(pattern)
    try:
        output = await _run_git(*args)
    except RuntimeError:
        return {}
    refs: dict[str, str] = {}
    for line in output.strip().splitlines():
        if not line:
            continue
        sha, ref = line.split(None, 1)
        refs[ref] = sha
    return refs


async def get_main_sha(auth_url: str) -> str | None:
    """Get the SHA of refs/heads/main, or None if it doesn't exist."""
    refs = await list_remote_refs(auth_url, "refs/heads/main")
    return refs.get("refs/heads/main")


async def ensure_repo_ready(
    token: str,
    repo_url: str,
    *,
    patronus: bool = False,
) -> None:
    """Ensure repo is in a known good state for testing.

    1. If empty, push an initial commit to main.
    2. If patronus, ensure .patronus/config.yaml exists on main.
    3. Delete all leftover test/* branches.

    For Patronus repos with branch protection on main, bootstrap failures
    are logged but not fatal — the repo must be set up manually.
    """
    auth_url = authenticated_url(repo_url, token)

    # 1. Ensure main exists with at least one commit
    main_sha = await get_main_sha(auth_url)
    if main_sha is None:
        try:
            await _bootstrap_empty_repo(auth_url, patronus=patronus)
        except RuntimeError as exc:
            if "permission" in str(exc).lower() or "rejected" in str(exc).lower():
                import warnings
                warnings.warn(
                    f"Cannot bootstrap {repo_url} — push to main denied "
                    f"(likely branch protection). Push initial commit manually.",
                    stacklevel=2,
                )
            else:
                raise
    elif patronus:
        try:
            await _ensure_patronus_config(auth_url)
        except RuntimeError as exc:
            if "permission" in str(exc).lower() or "rejected" in str(exc).lower():
                pass  # Branch protection — config must be pushed manually
            else:
                raise

    # 2. Clean up leftover test branches
    refs = await list_remote_refs(auth_url, "refs/heads/test/*")
    for ref in refs:
        branch = ref.removeprefix("refs/heads/")
        await delete_branch(token, repo_url, branch)


async def _bootstrap_empty_repo(auth_url: str, *, patronus: bool = False) -> None:
    """Ensure repo has a main branch with at least one commit.

    Uses --force to handle the case where the remote has diverged content
    (e.g., from a previous partial bootstrap).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Try cloning first — the repo may have content on a non-main branch
        try:
            await _run_git("clone", auth_url, tmpdir)
            # If clone succeeded, just ensure main exists
            await _run_git("config", "user.email", "test@space-mcp.test", cwd=tmpdir)
            await _run_git("config", "user.name", "space-mcp-test", cwd=tmpdir)
            # Try to checkout or create main
            try:
                await _run_git("checkout", "main", cwd=tmpdir)
            except RuntimeError:
                await _run_git("checkout", "-b", "main", cwd=tmpdir)
        except RuntimeError:
            # Clone failed — truly empty repo, init from scratch
            await _run_git("init", "--initial-branch=main", cwd=tmpdir)
            await _run_git("config", "user.email", "test@space-mcp.test", cwd=tmpdir)
            await _run_git("config", "user.name", "space-mcp-test", cwd=tmpdir)
            await _run_git("remote", "add", "origin", auth_url, cwd=tmpdir)

        (Path(tmpdir) / ".gitkeep").touch()
        await _run_git("add", ".gitkeep", cwd=tmpdir)

        if patronus:
            patronus_dir = Path(tmpdir) / ".patronus"
            patronus_dir.mkdir(exist_ok=True)
            (patronus_dir / "config.yaml").write_text(
                "version: '1.0'\nchecks: []\n"
            )
            await _run_git("add", ".patronus/config.yaml", cwd=tmpdir)

        # Check if there's anything to commit
        status = await _run_git("status", "--porcelain", cwd=tmpdir)
        if status.strip():
            await _run_git("commit", "-m", "Initial commit", cwd=tmpdir)

        await _run_git("push", "--force", "-u", "origin", "main", cwd=tmpdir)


async def _ensure_patronus_config(auth_url: str) -> None:
    """Ensure .patronus/config.yaml exists on main. Push it if missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        await _run_git("clone", "--depth=1", "--branch=main", auth_url, tmpdir)
        config_path = Path(tmpdir) / ".patronus" / "config.yaml"
        if config_path.exists():
            return

        await _run_git("config", "user.email", "test@space-mcp.test", cwd=tmpdir)
        await _run_git("config", "user.name", "space-mcp-test", cwd=tmpdir)

        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text("version: '1.0'\nchecks: []\n")
        await _run_git("add", ".patronus/config.yaml", cwd=tmpdir)
        await _run_git("commit", "-m", "Add Patronus config for testing", cwd=tmpdir)
        await _run_git("push", "origin", "main", cwd=tmpdir)


async def create_test_branch(token: str, repo_url: str, branch_name: str) -> None:
    """Create a branch at main HEAD on the remote and push a test commit."""
    auth_url = authenticated_url(repo_url, token)
    with tempfile.TemporaryDirectory() as tmpdir:
        await _run_git("clone", "--depth=1", "--branch=main", auth_url, tmpdir)
        await _run_git("config", "user.email", "test@space-mcp.test", cwd=tmpdir)
        await _run_git("config", "user.name", "space-mcp-test", cwd=tmpdir)
        await _run_git("checkout", "-b", branch_name, cwd=tmpdir)
        await _run_git("push", "-u", "origin", branch_name, cwd=tmpdir)


async def push_test_commit(token: str, repo_url: str, branch_name: str) -> None:
    """Push a test commit to an existing branch so it's ahead of main."""
    auth_url = authenticated_url(repo_url, token)
    with tempfile.TemporaryDirectory() as tmpdir:
        await _run_git("clone", "--depth=1", f"--branch={branch_name}", auth_url, tmpdir)
        await _run_git("config", "user.email", "test@space-mcp.test", cwd=tmpdir)
        await _run_git("config", "user.name", "space-mcp-test", cwd=tmpdir)

        test_file = Path(tmpdir) / "test-commit.txt"
        test_file.write_text(f"Test commit for branch {branch_name}\n")
        await _run_git("add", "test-commit.txt", cwd=tmpdir)
        await _run_git("commit", "-m", f"Test commit on {branch_name}", cwd=tmpdir)
        await _run_git("push", "origin", branch_name, cwd=tmpdir)


async def get_head_commit(token: str, repo_url: str, branch: str) -> str:
    """Get the HEAD commit SHA for a branch on a remote repo."""
    auth_url = authenticated_url(repo_url, token)
    refs = await list_remote_refs(auth_url, f"refs/heads/{branch}")
    sha = refs.get(f"refs/heads/{branch}")
    if not sha:
        raise RuntimeError(f"Branch {branch} not found on {repo_url}")
    return sha


async def delete_branch(token: str, repo_url: str, branch_name: str) -> None:
    """Delete a remote branch. Silently ignores errors."""
    auth_url = authenticated_url(repo_url, token)
    try:
        await _run_git("push", auth_url, f":refs/heads/{branch_name}")
    except RuntimeError:
        pass
