"""CLI output for MRs Space gave no number: labelled by id, never `#0`, and no web link."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tests.factories import make_mr

from .conftest import run_cli

_ENV = {"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"}
_NUMBER_LESS = make_mr(number=0, id="123456")
_NO_LINK = "merge request id:123456 has no number, so it has no web link"


def _git_context():
    from space.context import GitContext
    return GitContext(project="ij", repo="ultimate", branch="azhukova/fix-auth")


@pytest.mark.parametrize(("mr", "header"), [(_NUMBER_LESS, "id:123456 "), (make_mr(), "#188120 ")],
                         ids=["number-less", "numbered"])
def test_view_header(mr, header):
    with patch("space.cli.mr.resolve_mr_with_project", new_callable=AsyncMock, return_value=(mr, "ij")):
        result = run_cli("mr", "view", env=_ENV)
    assert result.exit_code == 0
    assert result.output.splitlines()[0] == f"{header}Fix authentication bug"


def test_view_web_of_number_less_mr_is_an_error():
    with patch("space.cli.mr.resolve_mr_with_project", new_callable=AsyncMock, return_value=(_NUMBER_LESS, "ij")), \
            patch("space.cli.mr.click.launch") as launch:
        result = run_cli("mr", "view", "--web", env=_ENV)
    assert result.exit_code == 1
    assert _NO_LINK in result.output
    launch.assert_not_called()


@pytest.mark.parametrize(("mr", "header"), [(_NUMBER_LESS, "id:123456"), (make_mr(), "#188120")],
                         ids=["number-less", "numbered"])
def test_status_header(mr, header):
    with patch("space.client.SpaceClient.find_merge_request_by_branch", new_callable=AsyncMock, return_value=mr), \
            patch("space.patronus.PatronusClient.list_runs_for_review", new_callable=AsyncMock, return_value=[]), \
            patch("space.context.detect_git_context", side_effect=_git_context):
        result = run_cli("status", env=_ENV)
    assert result.exit_code == 0
    assert f"Merge Request {header}: Fix authentication bug [Opened]" in result.output


@pytest.mark.parametrize(("mr", "line"), [(_NUMBER_LESS, "Created id:123456 T"), (make_mr(), "Created #188120 T")],
                         ids=["number-less", "numbered"])
def test_create_confirmation(mr, line):
    with patch("space.client.SpaceClient.create_merge_request", new_callable=AsyncMock, return_value=mr), \
            patch("space.context.detect_git_context", side_effect=_git_context):
        result = run_cli("mr", "create", "-t", "T", env=_ENV)
    assert result.exit_code == 0
    assert result.output.splitlines()[0] == line


def test_create_web_of_number_less_mr_is_an_error():
    with patch("space.client.SpaceClient.create_merge_request", new_callable=AsyncMock, return_value=_NUMBER_LESS), \
            patch("space.context.detect_git_context", side_effect=_git_context), \
            patch("space.cli.mr_actions.click.launch") as launch:
        result = run_cli("mr", "create", "-t", "T", "--web", env=_ENV)
    assert result.exit_code == 1
    assert "Created id:123456 T" in result.output
    assert _NO_LINK in result.output
    launch.assert_not_called()


def test_create_web_of_numbered_mr_opens_its_page():
    with patch("space.client.SpaceClient.create_merge_request", new_callable=AsyncMock, return_value=make_mr()), \
            patch("space.context.detect_git_context", side_effect=_git_context), \
            patch("space.cli.mr_actions.click.launch") as launch:
        result = run_cli("mr", "create", "-t", "T", "--web", env=_ENV)
    assert result.exit_code == 0
    launch.assert_called_once_with("https://jetbrains.team/p/ij/reviews/188120/timeline")
