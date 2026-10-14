"""Shared formatting utilities."""

import httpx


def human_size(n: int | None) -> str:
    """Format byte count as human-readable size (e.g. '4.0 KB')."""
    if n is None:
        return ""
    if n < 1024:
        return f"{n} B"
    size: float = n
    for unit in ("KB", "MB", "GB"):
        size /= 1024
        if size < 1024:
            return f"{size:.1f} {unit}"
    return f"{size:.1f} TB"


def describe_error(exc: BaseException) -> str:
    """One-line error text without a trailing period that cannot itself raise."""
    try:
        text = f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else str(exc)
    except Exception:
        return type(exc).__name__
    text = " ".join(text.split()).removesuffix(".")
    return text or type(exc).__name__
