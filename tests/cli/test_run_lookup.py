"""Patronus run lookup by MR number in `mr checks`, `run list` and `status`."""

from __future__ import annotations

import json
import re
from unittest.mock import AsyncMock, patch

import pytest

from tests.factories import make_mr
from tests.sample_responses import wire_run

from .conftest import run_cli

_ENV = {"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"}
_ROBOTS = re.compile(r"https://patronus\.labs\.jb\.gg/app/rest/v1/robots(\?|$)")
_NO_NUMBER = "Merge request id:123456 has no number, so its Patronus runs cannot be looked up."
_NUMBER_LESS = make_mr(number=0, id="123456")


def _git_context():
    from space.context import GitContext
    return GitContext(project="ij", repo="ultimate", branch="azhukova/fix-auth")


def _command(name: str, mr):
    """Run a lookup command with `mr` as the MR it resolves."""
    if name == "mr checks":
        target = patch("space.cli.mr.resolve_mr_with_project", new_callable=AsyncMock, return_value=(mr, "ij"))
    else:
        target = patch("space.client.SpaceClient.find_merge_request_by_branch", new_callable=AsyncMock, return_value=mr)
    with target, patch("space.context.detect_git_context", side_effect=_git_context):
        return run_cli(*name.split(), env=_ENV)


@pytest.mark.parametrize("name", ["mr checks", "run list", "status"])
def test_numbered_mr_runs_are_looked_up_by_number(name):
    with patch("space.patronus.PatronusClient.list_runs_for_review", new_callable=AsyncMock, return_value=[]) as runs:
        result = _command(name, make_mr())
    assert result.exit_code == 0
    assert runs.await_args.args[:2] == ("ij", 188120)


class TestNumberLessMr:

    @pytest.fixture(autouse=True)
    def _other_mrs_run(self, httpx_mock):
        """A run of the MR whose number equals this MR's all-digit id: it must never be fetched."""
        httpx_mock.add_response(
            url=_ROBOTS,
            json={
                "robots": [wire_run("SUCCESS", spaceReviewUrl="https://jetbrains.team/p/ij/reviews/123456/timeline")]
            },
            is_optional=True,
        )
        yield
        assert httpx_mock.get_requests(url=_ROBOTS) == []

    @pytest.mark.parametrize("name", ["mr checks", "run list"])
    def test_lookup_fails_with_a_clear_message(self, name):
        result = _command(name, _NUMBER_LESS)
        assert result.exit_code == 1
        assert _NO_NUMBER in result.output

    def test_status_says_why_and_succeeds(self):
        result = _command("status", _NUMBER_LESS)
        assert result.exit_code == 0
        assert _NO_NUMBER in result.output

    def test_status_json_says_why(self):
        with patch(
            "space.client.SpaceClient.find_merge_request_by_branch", new_callable=AsyncMock, return_value=_NUMBER_LESS
        ), patch("space.context.detect_git_context", side_effect=_git_context):
            result = run_cli("--json", "", "status", env=_ENV)
        assert result.exit_code == 0
        data = json.loads(result.output[result.output.index("\n{") + 1:])
        assert data["latest_run"] is None
        assert data["latest_run_unavailable"] == "merge request has no number"
