"""Authentication and credential storage for the Space CLI and MCP server.

Resolves authentication tokens from environment, OS keyring, and stored credentials.
"""

import json
import os
import threading
from pathlib import Path

from .context import SPACE_URL


class AuthenticationError(Exception):
    """Raised when no authentication token can be resolved."""


_CREDENTIALS_FILE = Path.home() / ".config" / "space" / "credentials.json"
_KEYRING_TIMEOUT = 3  # seconds — prevents hang on headless Linux (D-Bus)
_KEYRING_USERNAME = "token"  # fixed key; we don't know the Space username at login
_KEYRING_SERVICE = f"space:{SPACE_URL}"


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


# Keyring operations -----


def _keyring_get() -> str | None:
    """Get token from OS keyring. Returns None if unavailable."""
    try:
        import keyring
        return _keyring_call(keyring.get_password, _KEYRING_SERVICE, _KEYRING_USERNAME)
    except Exception:  # keyring may be unavailable (no backend, dbus error, etc.)
        return None


def _keyring_set(token: str) -> bool:
    """Store token in OS keyring. Returns True on success."""
    try:
        import keyring
        _keyring_call(keyring.set_password, _KEYRING_SERVICE, _KEYRING_USERNAME, token)
        return True
    except Exception:  # keyring may be unavailable (no backend, dbus error, etc.)
        return False


def _keyring_delete() -> bool:
    """Delete token from OS keyring. Returns True on success."""
    try:
        import keyring
        _keyring_call(keyring.delete_password, _KEYRING_SERVICE, _KEYRING_USERNAME)
        return True
    except Exception:  # keyring may be unavailable (no backend, dbus error, etc.)
        return False


# File-based storage -----


def load_stored_token() -> str | None:
    """Load token from stored credentials file (~/.config/space/credentials.json)."""
    if not _CREDENTIALS_FILE.exists():
        return None
    try:
        creds = json.loads(_CREDENTIALS_FILE.read_text())
        return creds.get(SPACE_URL, {}).get("token")
    except (json.JSONDecodeError, OSError):
        return None


def _file_store(token: str) -> None:
    """Store token in the plaintext credentials file."""
    _CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    creds = {}
    if _CREDENTIALS_FILE.exists():
        try:
            creds = json.loads(_CREDENTIALS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    creds[SPACE_URL] = {"token": token}
    _CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2))
    _CREDENTIALS_FILE.chmod(0o600)


def _file_delete() -> bool:
    """Remove token from the credentials file. Returns True if it was present."""
    if not _CREDENTIALS_FILE.exists():
        return False
    try:
        creds = json.loads(_CREDENTIALS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    if SPACE_URL not in creds:
        return False
    del creds[SPACE_URL]
    if creds:
        _CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2))
    else:
        _CREDENTIALS_FILE.unlink()
    return True


# High-level API -----


def resolve_token() -> str | None:
    """Resolve authentication token.

    Priority (highest first):
    1. SPACE_TOKEN environment variable
    2. OS keyring
    3. Plaintext credentials file
    """
    return os.environ.get("SPACE_TOKEN") or _keyring_get() or load_stored_token()


def resolve_token_source() -> str | None:
    """Return the source of the active token: 'env', 'keyring', 'config', or None."""
    if os.environ.get("SPACE_TOKEN"):
        return "env"
    if _keyring_get():
        return "keyring"
    if load_stored_token():
        return "config"
    return None


def store_token(token: str, *, insecure: bool = False) -> tuple[bool, str]:
    """Store a token securely.

    Returns (used_keyring, description) where:
    - used_keyring is True if the token was stored in the OS keyring
    - description is a human-readable string for the storage location

    If insecure=False (default), tries keyring first, falls back to file.
    If insecure=True, writes directly to the plaintext file.
    """
    if not insecure:
        if _keyring_set(token):
            # Remove any leftover file-based token
            _file_delete()
            return True, "system keyring"

    # Keyring failed or --insecure-storage: write to file
    _file_store(token)
    return False, str(_CREDENTIALS_FILE)


def delete_token() -> None:
    """Delete stored token from keyring and/or file.

    Raises RuntimeError if the token cannot be fully removed.
    """
    errors: list[str] = []
    found = False

    # Try keyring
    has_keyring = _keyring_get() is not None
    if has_keyring:
        found = True
        if not _keyring_delete():
            errors.append("Failed to remove token from system keyring.")

    # Try file
    has_file = load_stored_token() is not None
    if has_file:
        found = True
        if not _file_delete():
            errors.append(f"Failed to remove token from {_CREDENTIALS_FILE}.")

    if not found:
        raise RuntimeError("No credentials found.")
    if errors:
        raise RuntimeError(" ".join(errors))
