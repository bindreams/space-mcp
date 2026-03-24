"""Terminal output formatting for the Space CLI.

Handles colored text, tables, and JSON output.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime
from typing import Any

import click


def is_tty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


# JSON output =====


def _json_default(obj: Any) -> Any:
    """Custom JSON serializer for dataclass instances and datetimes."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        d = dataclasses.asdict(obj)
        # Add computed 'name' property for SpacePrincipal subclasses
        if hasattr(obj, "name") and "name" not in d:
            d["name"] = obj.name
        return d
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def print_json(data: Any, fields: str | None = None) -> None:
    """Print data as JSON, optionally filtering to specific fields."""
    # Convert dataclass to dict for field filtering
    if dataclasses.is_dataclass(data) and not isinstance(data, type):
        data = _json_default(data)

    if fields and isinstance(data, dict):
        keys = [k.strip() for k in fields.split(",")]
        data = {k: v for k, v in data.items() if k in keys}
    elif fields and isinstance(data, list):
        keys = [k.strip() for k in fields.split(",")]
        data = [
            {k: v for k, v in (_json_default(item) if dataclasses.is_dataclass(item) else item).items() if k in keys}
            for item in data
        ]
    click.echo(json.dumps(data, indent=2, default=_json_default))


# Table output =====


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


# Status styling =====


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


# Reviewer state symbols =====


_REVIEW_SYMBOLS = {
    "Accepted": "✓",
    "Rejected": "✗",
    "Resumed": "○",
    "Pending": "○",
}


def reviewer_symbol(state: str) -> str:
    return _REVIEW_SYMBOLS.get(state, "○")


# Timestamp helpers =====


def format_datetime(dt: datetime | None, fmt: str = "%b %d, %H:%M") -> str:
    """Format a datetime in local timezone."""
    if dt is None:
        return ""
    return dt.astimezone().strftime(fmt)


def format_datetime_date(dt: datetime | None) -> str:
    """Format datetime as 'January 15, 2026'."""
    if dt is None:
        return ""
    return dt.astimezone().strftime("%B %d, %Y").replace(" 0", " ")


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
