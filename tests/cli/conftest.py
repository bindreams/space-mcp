"""Shared CLI test helpers."""

from __future__ import annotations

from click.testing import CliRunner

from space.__main__ import main


def run_cli(*args: str, env: dict | None = None, input: str | None = None) -> object:
    """Run a CLI command and return the result."""
    runner = CliRunner()
    return runner.invoke(main, list(args), env=env or {}, input=input, catch_exceptions=False)


RUN_ID = "cc448634-880e-411f-9ee6-347e9a6087ac"


def patronus_url(path: str) -> str:
    """Absolute URL the CLI's PatronusClient requests (it ignores PATRONUS_URL, so the production default)."""
    from space.patronus import PatronusClient

    return f"{PatronusClient('test').base_url}{path}"


def mock_run_responses(httpx_mock, run_wire: dict, check_wires: list[dict], *, problems: bool = False) -> None:
    """Register the Patronus responses `run view` / `run watch` request for one run."""
    run_id = run_wire["id"]
    httpx_mock.add_response(url=patronus_url(f"/app/rest/v1/robots/{run_id}"), json=run_wire)
    httpx_mock.add_response(
        url=patronus_url(f"/app/rest/v1/robots/{run_id}/teamcity-checks"),
        json={"robotId": run_id, "teamCityChecks": check_wires},
    )
    if problems:
        httpx_mock.add_response(url=patronus_url(f"/app/rest/v1/robots/{run_id}/problems"), json={"problems": []})
