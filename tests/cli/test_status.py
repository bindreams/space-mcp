"""Tests for the `space status` dashboard."""

from __future__ import annotations

from unittest.mock import patch

from tests.sample_responses import wire_check, wire_run

from .conftest import RUN_ID, patronus_url, run_cli


@patch("space.client.SpaceClient.find_merge_request_by_branch", return_value=None)
@patch("space.context.detect_git_context")
def test_dashboard_running_run_with_queued_check_shows_running(mock_ctx, mock_find, httpx_mock, test_accounts):
    from space.context import GitContext
    mock_ctx.return_value = GitContext(project="ij", repo="ultimate", branch="feat")
    httpx_mock.add_response(
        url=patronus_url("/app/rest/v1/robots"),
        match_params={"sourceBranch": "feat"},
        json={"robots": [wire_run("RUNNING")]},
    )
    httpx_mock.add_response(
        url=patronus_url(f"/app/rest/v1/robots/{RUN_ID}/teamcity-checks"),
        json={"robotId": RUN_ID, "teamCityChecks": [wire_check("QUEUED")]},
    )

    result = run_cli("status", env={"SPACE_TOKEN": "test"})

    latest = next(line for line in result.output.splitlines() if line.startswith("Latest Run:"))
    assert latest.endswith("[RUNNING] (DRY_RUN)")
    assert "UNKNOWN" not in result.output
