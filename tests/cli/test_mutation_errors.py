"""CLI errors for a mutation Space confirmed: say it took effect, never suggest re-running it."""

from __future__ import annotations

import re
import shlex
from unittest.mock import patch

import pytest

from tests.factories import make_mr
from tests.sample_responses import SAMPLE_CREATED_MERGE_REQUEST, SAMPLE_MERGE_REQUEST

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


_START_COMMANDS = [
    pytest.param(("run", "start", "42"), "space.cli.run.resolve_mr_with_project", id="run-start"),
    pytest.param(("mr", "merge", "42"), "space.cli.mr_actions.resolve_mr_with_project", id="mr-merge"),
]


class TestSafeMergeStart:

    @pytest.mark.parametrize(("args", "resolver"), _START_COMMANDS)
    @pytest.mark.parametrize("body", [b"not json", b'{"status": ["x"]}'], ids=["invalid-json", "bad-status"])
    def test_unreadable_response_says_a_run_may_have_started(self, httpx_mock, args, resolver, body):
        httpx_mock.add_response(method="POST", content=body)

        with patch(resolver, return_value=(make_mr(number=42, id="4Xa1b2"), "ij")):
            result = run_cli(*args, env=_ENV)

        assert result.exit_code == 1
        assert "Error: Space accepted the safe-merge request for merge request #42, " in result.output
        assert (
            "A run may have started; do not re-run it before checking. "
            "Check with `space -P ij -R ultimate mr checks 42`." in result.output
        )
        (post, ) = httpx_mock.get_requests(method="POST")
        assert b'"mergeRequestId": "id:4Xa1b2"' in post.content or b'"mergeRequestId":"id:4Xa1b2"' in post.content

    @pytest.mark.parametrize(("args", "resolver"), _START_COMMANDS)
    def test_numberless_mr_gets_the_fixed_sentence(self, httpx_mock, args, resolver):
        httpx_mock.add_response(method="POST", content=b"not json")

        with patch(resolver, return_value=(make_mr(number=0, id="4Xa1b2"), "ij")):
            result = run_cli(*args, env=_ENV)

        assert "Error: Space accepted the safe-merge request for merge request id:4Xa1b2, " in result.output
        assert (
            "A run may have started; do not re-run it before checking. "
            "Check the merge request's Patronus runs before re-running." in result.output
        )

    @pytest.mark.parametrize(("args", "resolver"), _START_COMMANDS)
    def test_start_passes_the_internal_id_as_an_id(self, httpx_mock, args, resolver):
        httpx_mock.add_response(method="POST", json={"robotId": "r1", "status": "RUNNING"})

        with patch(resolver, return_value=(make_mr(number=42, id="123456"), "ij")):
            result = run_cli(*args, env=_ENV)

        assert result.exit_code == 0
        assert [r.method for r in httpx_mock.get_requests()] == ["POST"]
        assert b"id:123456" in httpx_mock.get_requests()[0].content


class TestStartPrintsTheRun:

    @pytest.mark.parametrize(
        ("body", "lines"),
        [
            (
                {"robotId": "r1", "robotUrl": "https://p/robot/r1", "status": "RUNNING"},
                ["Dry run started: RUNNING", "Run ID: r1", "Patronus: https://p/robot/r1"],
            ),
            ({}, ["Dry run started: ?", "Run ID: ?", "Patronus: https://patronus.labs.jb.gg/robot/?"]),
            ([], []),
            ([{"type": "Progress", "message": "queued"}], ["queued"]),
        ],
        ids=["dict", "empty-dict", "empty-list", "progress"],
    )
    def test_start_output(self, httpx_mock, body, lines):
        httpx_mock.add_response(method="POST", json=body)

        with patch("space.cli.run.resolve_mr_with_project", return_value=(make_mr(number=42, id="4Xa1b2"), "ij")):
            result = run_cli("run", "start", "42", env=_ENV)

        assert result.exit_code == 0
        assert result.output.splitlines() == lines

    def test_error_event_is_a_click_error(self, httpx_mock):
        httpx_mock.add_response(method="POST", json=[{"type": "Error", "message": "Robot already exists"}])

        with patch("space.cli.run.resolve_mr_with_project", return_value=(make_mr(number=42, id="4Xa1b2"), "ij")):
            result = run_cli("run", "start", "42", env=_ENV)

        assert result.exit_code == 1
        assert "Error: A dry run or merge is already in progress for this merge request." in result.output


class TestCommentAndDiscussion:

    @pytest.mark.parametrize(
        ("args", "lead"),
        [
            (("mr", "comment", "42", "hi"), "The comment was posted; do not re-run it."),
            (
                ("mr", "discuss", "42", "hi", "--file", "f", "--line", "1", "--revision", "r"),
                "The code discussion was created; do not re-run it.",
            ),
        ],
        ids=["comment", "discuss"],
    )
    def test_unreadable_response_names_the_timeline(self, httpx_mock, args, lead):
        if args[1] == "comment":
            httpx_mock.add_response(method="GET", json={"feedChannel": {"id": "ch1"}})
        httpx_mock.add_response(method="POST", json={})

        with patch("space.cli.mr_actions.resolve_mr_with_project", return_value=(make_mr(number=42), "ij")):
            result = run_cli(*args, env=_ENV)

        assert result.exit_code == 1
        assert f"{lead} See it with `space -P ij -R ultimate mr timeline 42`." in result.output


@pytest.mark.raises_unrecognised_api_value
class TestStrictCause:
    """A strict failure after the mutation: the inspect command must also turn strict off."""

    @pytest.mark.parametrize(("number", "label"), [(194200, "194200"), (None, "id:abc123")], ids=["number", "id"])
    def test_create(self, httpx_mock, number, label):
        body = {**SAMPLE_CREATED_MERGE_REQUEST, "state": "NEW_STATE"}
        if number is None:
            del body["number"]
        httpx_mock.add_response(method="POST", json=body)

        result = run_cli("mr", "create", _BRANCH, "-t", "T", env=_ENV)

        assert result.exit_code == 1
        assert "reading it failed: MRState: unrecognised value 'NEW_STATE' (strict mode)" in result.output
        assert f"Inspect it with `space --no-strict -P ij -R ultimate mr view {label}`." in result.output
        assert "Run as" not in result.output

    @pytest.mark.parametrize(
        ("mr", "label"),
        [(make_mr(number=42), "42"), (make_mr(number=0, id="4Xa1b2"), "id:4Xa1b2")],
        ids=["number", "id"],
    )
    def test_edit(self, httpx_mock, test_accounts, mr, label):
        httpx_mock.add_response(method="PATCH", json={})
        httpx_mock.add_response(method="GET", json={**SAMPLE_MERGE_REQUEST, "state": "NEW_STATE"})

        with patch("space.cli.mr_actions.resolve_mr_with_project", return_value=(mr, "ij")):
            result = run_cli("mr", "edit", label, "-t", "T", env=_ENV)

        assert result.exit_code == 1
        assert f"Inspect it with `space --no-strict -P ij -R ultimate mr view {label}`." in result.output
        assert "Run as" not in result.output
