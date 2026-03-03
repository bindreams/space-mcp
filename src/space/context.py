"""Context inference and authentication for the Space CLI and MCP server.

Detects project, repository, and branch from git remote URLs and HEAD.
Resolves authentication tokens from environment and stored credentials.
"""

import json
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

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


# Authentication ==============================================================


class AuthenticationError(Exception):
    """Raised when no authentication token can be resolved."""


_CREDENTIALS_FILE = Path.home() / ".config" / "space" / "credentials.json"
_KEYRING_TIMEOUT = 3  # seconds — prevents hang on headless Linux (D-Bus)
_KEYRING_USERNAME = "token"  # fixed key; we don't know the Space username at login


def _keyring_service(url: str) -> str:
    """Keyring service name for a Space instance URL."""
    return f"space:{url}"


def _keyring_call(fn, *args, timeout: int = _KEYRING_TIMEOUT):
    """Run a keyring operation with a timeout.

    Returns the result, or None on timeout. Re-raises any exception from the
    keyring backend (callers should catch as needed).
    """
    result = [None]
    error = [None]

    def target():
        try:
            result[0] = fn(*args)
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None  # timeout — treat as unavailable
    if error[0] is not None:
        raise error[0]
    return result[0]


# Keyring operations ----------------------------------------------------------


def _keyring_get(url: str) -> str | None:
    """Get token from OS keyring. Returns None if unavailable."""
    try:
        import keyring
        return _keyring_call(keyring.get_password, _keyring_service(url), _KEYRING_USERNAME)
    except Exception:
        return None


def _keyring_set(url: str, token: str) -> bool:
    """Store token in OS keyring. Returns True on success."""
    try:
        import keyring
        _keyring_call(keyring.set_password, _keyring_service(url), _KEYRING_USERNAME, token)
        return True
    except Exception:
        return False


def _keyring_delete(url: str) -> bool:
    """Delete token from OS keyring. Returns True on success."""
    try:
        import keyring
        _keyring_call(keyring.delete_password, _keyring_service(url), _KEYRING_USERNAME)
        return True
    except Exception:
        return False


# File-based storage ----------------------------------------------------------


def load_stored_token(url: str = "https://jetbrains.team") -> str | None:
    """Load token from stored credentials file (~/.config/space/credentials.json)."""
    if not _CREDENTIALS_FILE.exists():
        return None
    try:
        creds = json.loads(_CREDENTIALS_FILE.read_text())
        return creds.get(url, {}).get("token")
    except (json.JSONDecodeError, OSError):
        return None


def _file_store(url: str, token: str) -> None:
    """Store token in the plaintext credentials file."""
    _CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    creds = {}
    if _CREDENTIALS_FILE.exists():
        try:
            creds = json.loads(_CREDENTIALS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    creds[url] = {"token": token}
    _CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2))
    _CREDENTIALS_FILE.chmod(0o600)


def _file_delete(url: str) -> bool:
    """Remove token for a URL from the credentials file. Returns True if it was present."""
    if not _CREDENTIALS_FILE.exists():
        return False
    try:
        creds = json.loads(_CREDENTIALS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    if url not in creds:
        return False
    del creds[url]
    if creds:
        _CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2))
    else:
        _CREDENTIALS_FILE.unlink()
    return True


# High-level API --------------------------------------------------------------


def resolve_token(url: str = "https://jetbrains.team") -> str | None:
    """Resolve authentication token.

    Priority (highest first):
    1. SPACE_TOKEN environment variable
    2. OS keyring
    3. Plaintext credentials file
    """
    return os.environ.get("SPACE_TOKEN") or _keyring_get(url) or load_stored_token(url)


def resolve_token_source(url: str = "https://jetbrains.team") -> str | None:
    """Return the source of the active token: 'env', 'keyring', 'config', or None."""
    if os.environ.get("SPACE_TOKEN"):
        return "env"
    if _keyring_get(url):
        return "keyring"
    if load_stored_token(url):
        return "config"
    return None


def store_token(url: str, token: str, *, insecure: bool = False) -> tuple[bool, str]:
    """Store a token securely.

    Returns (used_keyring, description) where:
    - used_keyring is True if the token was stored in the OS keyring
    - description is a human-readable string for the storage location

    If insecure=False (default), tries keyring first, falls back to file.
    If insecure=True, writes directly to the plaintext file.
    """
    if not insecure:
        if _keyring_set(url, token):
            # Remove any leftover file-based token for this URL
            _file_delete(url)
            return True, "system keyring"

    # Keyring failed or --insecure-storage: write to file
    _file_store(url, token)
    return False, str(_CREDENTIALS_FILE)


def delete_token(url: str = "https://jetbrains.team") -> None:
    """Delete stored token from keyring and/or file.

    Raises RuntimeError if the token cannot be fully removed.
    """
    errors: list[str] = []
    found = False

    # Try keyring
    has_keyring = _keyring_get(url) is not None
    if has_keyring:
        found = True
        if not _keyring_delete(url):
            errors.append("Failed to remove token from system keyring.")

    # Try file
    has_file = load_stored_token(url) is not None
    if has_file:
        found = True
        if not _file_delete(url):
            errors.append(f"Failed to remove token from {_CREDENTIALS_FILE}.")

    if not found:
        raise RuntimeError(f"No credentials found for {url}.")
    if errors:
        raise RuntimeError(" ".join(errors))
