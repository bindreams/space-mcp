"""Terminal output formatting for the Space CLI.

Handles colored text, tables, and JSON output.
"""

import json
import sys
from datetime import datetime
from typing import Any

import click


def is_tty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


# JSON output =================================================================


def print_json(data: Any, fields: str | None = None) -> None:
    """Print data as JSON, optionally filtering to specific fields."""
    if fields and isinstance(data, dict):
        keys = [k.strip() for k in fields.split(",")]
        data = {k: v for k, v in data.items() if k in keys}
    elif fields and isinstance(data, list):
        keys = [k.strip() for k in fields.split(",")]
        data = [{k: v for k, v in item.items() if k in keys} for item in data]
    click.echo(json.dumps(data, indent=2, default=str))


# Table output ================================================================


def print_table(headers: list[str], rows: list[list[str]], *, max_widths: dict[int, int] | None = None) -> None:
    """Print a formatted table with optional column width limits."""
    if not rows:
        return

    max_widths = max_widths or {}

    # Calculate column widths -----
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))

    # Apply max width constraints
    for col, max_w in max_widths.items():
        if col < len(widths):
            widths[col] = min(widths[col], max_w)

    def _truncate(text: str, width: int) -> str:
        if len(text) <= width:
            return text.ljust(width)
        return text[:width - 1] + "…"

    # Header -----
    header_line = "  ".join(_truncate(h, widths[i]) for i, h in enumerate(headers))
    click.secho(header_line, bold=True)
    click.echo("  ".join("─" * widths[i] for i in range(len(headers))))

    # Rows -----
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            width = widths[i] if i < len(widths) else len(cell)
            cells.append(_truncate(cell, width))
        click.echo("  ".join(cells))


# Status styling ==============================================================


_STATUS_COLORS = {
    "Opened": "green", "Open": "green",
    "Closed": "red",
    "Merged": "cyan",
    "SUCCESS": "green", "SUCCESSFUL": "green",
    "FAILURE": "red", "FAILED": "red",
    "RUNNING": "yellow",
    "CANCELLED": "white",
    "PENDING": "white",
}


def styled_status(status: str) -> str:
    color = _STATUS_COLORS.get(status)
    if color and is_tty():
        return click.style(status, fg=color)
    return status


# Reviewer state symbols ======================================================


_REVIEW_SYMBOLS = {
    "Accepted": "✓",
    "Rejected": "✗",
    "Resumed": "○",
    None: "○",
}


def reviewer_symbol(state: str | None) -> str:
    return _REVIEW_SYMBOLS.get(state, "○")


# Timestamp helpers ===========================================================


def format_iso(iso_str: str | None) -> str:
    """Format ISO timestamp as 'Jan 15, 08:00'."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%b %d, %H:%M")
    except (ValueError, TypeError):
        return iso_str[:16] if iso_str else ""


def format_epoch_ms(epoch_ms: int | None) -> str:
    """Format epoch milliseconds as 'Jan 15, 08:00'."""
    if epoch_ms is None:
        return ""
    dt = datetime.fromtimestamp(epoch_ms / 1000).astimezone()
    return dt.strftime("%b %d, %H:%M")


def format_epoch_date(epoch_ms: int | None) -> str:
    """Format epoch milliseconds as 'January 15, 2026'."""
    if epoch_ms is None:
        return ""
    dt = datetime.fromtimestamp(epoch_ms / 1000).astimezone()
    return dt.strftime("%B %d, %Y").replace(" 0", " ")


# Domain-specific formatters ==================================================


def extract_name(created_by: dict[str, Any]) -> str:
    """Extract display name from createdBy field."""
    name = created_by.get("name")
    if isinstance(name, dict):
        first = name.get("firstName", "")
        last = name.get("lastName", "")
        return f"{first} {last}".strip() or created_by.get("username", "Unknown")
    return name or created_by.get("username", "Unknown")


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


def extract_author(author: dict[str, Any] | None) -> str:
    """Extract author name from author dict."""
    if not author:
        return "Unknown"
    return author.get("name") or author.get("username") or "Unknown"
