"""Shared CLI test helpers."""

from __future__ import annotations

from click.testing import CliRunner

from space.__main__ import main


def run_cli(*args: str, env: dict | None = None, input: str | None = None) -> object:
    """Run a CLI command and return the result."""
    runner = CliRunner()
    return runner.invoke(main, list(args), env=env or {}, input=input, catch_exceptions=False)
