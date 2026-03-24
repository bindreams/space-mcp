"""Shared formatting utilities."""


def human_size(n: int | None) -> str:
    """Format byte count as human-readable size (e.g. '4.0 KB')."""
    if n is None:
        return ""
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024
        if n < 1024:
            return f"{n:.1f} {unit}"
    return f"{n:.1f} TB"
