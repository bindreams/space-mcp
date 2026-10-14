"""CLI errors for a mutation Space confirmed: say it took effect, never suggest re-running it."""

from __future__ import annotations

import re
import shlex
from unittest.mock import patch

import pytest

from tests.factories import make_mr
from tests.sample_responses import SAMPLE_CREATED_MERGE_REQUEST

from .conftest import run_cli

_ENV = {"SPACE_TOKEN": "test", "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"}
_BRANCH = "azhukova/new-feature"


def _hint_command(output: str) -> list[str]:
    (command, ) = re.findall(r"`([^`]*)`\.", output)
    return shlex.split(command)


class TestCreate:

    @pytest.mark.parametrize(
        ("case", "message", "hint"),
        [
            (
                "number",
                "Error: merge request #194200 was created, but reading it failed: HTTP 500",
                "Inspect it with `space -P ij -R ultimate mr view 194200`.",
            ),
            (
                "id",
                "Error: merge request id:abc123 was created, but reading it failed: HTTP 500",
                "Inspect it with `space -P ij -R ultimate mr view id:abc123`.",
            ),
            (
                "invalid-json",
                "Error: a merge request was created, but reading it failed: Expecting value: line 1 column 1 (char 0)",
                f"Find it with `space -P ij -R ultimate mr list -H {_BRANCH}`.",
            ),
        ],
    )
    def test_unreadable_response_names_the_created_mr(self, httpx_mock, case, message, hint):
        if case == "invalid-json":
            httpx_mock.add_response(method="POST", content=b"not json")
        else:
            body = {**SAMPLE_CREATED_MERGE_REQUEST, "createdBy": {"id": "u1"}}
            if case == "id":
                del body["number"]
            httpx_mock.add_response(method="POST", json=body)
            httpx_mock.add_response(method="GET", status_code=500)

        result = run_cli("mr", "create", _BRANCH, "-t", "T", env=_ENV)

        assert result.exit_code == 1
        assert message in result.output
        assert f"The merge request was created; do not re-run the create. {hint}" in result.output
        assert "Run as" not in result.output

    def test_hint_quotes_shell_metacharacters(self, httpx_mock):
        httpx_mock.add_response(method="POST", content=b"not json")
        env = {**_ENV, "SPACE_PROJECT": "my proj", "SPACE_REPO": "a;b"}

        result = run_cli("mr", "create", "feat/it's here", "-t", "T", env=env)

        assert result.exit_code == 1
        assert _hint_command(result.output
                             ) == ["space", "-P", "my proj", "-R", "a;b", "mr", "list", "-H", "feat/it's here"]


class TestEdit:

    @pytest.mark.parametrize(
        ("mr", "label"),
        [(make_mr(number=42), "42"), (make_mr(number=0, id="4Xa1b2"), "id:4Xa1b2")],
        ids=["number", "id"],
    )
    def test_refetch_failure_says_the_edit_was_applied(self, httpx_mock, mr, label):
        httpx_mock.add_response(method="PATCH", json={})
        httpx_mock.add_response(method="GET", status_code=500)

        with patch("space.cli.mr_actions.resolve_mr_with_project", return_value=(mr, "ij")):
            result = run_cli("mr", "edit", label, "-t", "T", env=_ENV)

        assert result.exit_code == 1
        assert "Error: edit applied (title) but re-fetching the updated MR failed: HTTP 500" in result.output
        assert (
            f"The edit was applied; do not re-run it. Inspect it with `space -P ij -R ultimate mr view {label}`."
            in result.output
        )
        assert "Run as" not in result.output
        segment = "number:42" if label == "42" else "id:4Xa1b2"
        assert all(segment in str(request.url) for request in httpx_mock.get_requests())
