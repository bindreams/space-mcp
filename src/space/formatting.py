"""Shared formatting utilities."""


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
