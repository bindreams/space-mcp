"""Strict mode in the MCP server: resolved at start-up, and named in every strict error's hint."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import space.mcp.server as server_module
from space.client import SpaceClient
from space.mcp.server import SpaceMCP, _DRY_RUN_CHECK_HINT
from space.models import ReviewRef, TimelineEventClass, TimelineMessage, enums
from space.models.enums import UnrecognisedApiValue
from space.mutation import Mutation, MutationCompletedError, MutationTarget
from space.patronus import PatronusClient
from space.strict import StrictSetting, StrictSource
from tests.factories import make_account, make_dt

_RID = "917ff740-e579-409a-b4a2-3014ba96529b"
_ERROR = "**Error:** RunStatus: unrecognised value 'NEW' (strict mode)"
_TAIL = " to treat unrecognised values as UNKNOWN."


def _config(text: str) -> Path:
    path = Path(os.environ["XDG_CONFIG_HOME"]) / "space" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _restart(source: StrictSource | None, path: Path | None = None) -> str:
    if source is StrictSource.ENV:
        return "Set SPACE_STRICT=0 and restart the MCP server"
    if source is StrictSource.CONFIG:
        return f"Set strict: false in {json.dumps(str(path))} and restart the MCP server"
    return "Restart the MCP server with SPACE_STRICT=0"


def _setting(source: StrictSource | None, path: Path = Path("/cfg/space/config.yaml")) -> StrictSetting | None:
    if source is None:
        return None
    return StrictSetting(source is not StrictSource.DEFAULT, source, path if source is StrictSource.CONFIG else None)


_SOURCES = [StrictSource.ENV, StrictSource.CONFIG, StrictSource.DEFAULT, StrictSource.FLAG, None]


def _server(setting: StrictSetting | None) -> SpaceMCP:
    server = SpaceMCP(token="test-token", strict=setting)
    server.space_client = MagicMock()
    server.patronus_client = MagicMock()
    return server


# Start-up =============================================================================================================


class TestMain:

    @pytest.mark.parametrize("case", ["bad-env", "broken-config"])
    def test_main_exits_2_on_bad_settings(self, monkeypatch, capsys, case):

        def amain(setting):
            raise AssertionError("amain called")

        monkeypatch.setattr(server_module, "amain", amain)
        if case == "bad-env":
            monkeypatch.setenv("SPACE_STRICT", "maybe")
            first_line = 'SPACE_STRICT: expected 1, true, yes, on, 0, false, no or off, got "maybe"'
        else:
            monkeypatch.delenv("SPACE_STRICT")
            path = _config("strict: maybe\n")
            first_line = f"{json.dumps(str(path))}: strict: expected a boolean, got str"

        with pytest.raises(SystemExit) as info:
            server_module.main()

        assert info.value.code == 2
        assert capsys.readouterr().err == f"space-mcp: {first_line}\n"

    @pytest.mark.unrecognised_api_value
    @pytest.mark.parametrize("source", [StrictSource.ENV, StrictSource.CONFIG])
    def test_main_wires_the_setting_into_format_error(self, monkeypatch, source):
        recorded: list[object] = []

        async def run_stdio_async(self, *args, **kwargs):
            recorded.append(enums.is_strict())
            recorded.append(self.format_error(UnrecognisedApiValue("RunStatus", "NEW")))

        monkeypatch.setenv("SPACE_TOKEN", "test-token")
        monkeypatch.setattr(SpaceClient, "warmup", AsyncMock())
        monkeypatch.setattr(PatronusClient, "warmup", AsyncMock())
        monkeypatch.setattr(SpaceMCP, "run_stdio_async", run_stdio_async)
        path = None
        if source is StrictSource.ENV:
            monkeypatch.setenv("SPACE_STRICT", "1")
        else:
            monkeypatch.delenv("SPACE_STRICT")
            path = _config("strict: true\n")

        server_module.main()

        assert recorded == [True, f"{_ERROR}\n\n{_restart(source, path)}{_TAIL}"]


# Hints ================================================================================================================


class TestHints:

    @pytest.mark.parametrize("source", _SOURCES, ids=lambda s: s.name if s else "none")
    def test_strict_error_hint_names_the_source(self, source):
        server = _server(_setting(source))
        expected = f"{_ERROR}\n\n{_restart(source, Path('/cfg/space/config.yaml'))}{_TAIL}"
        assert server.format_error(UnrecognisedApiValue("RunStatus", "NEW")) == expected

    def test_config_hint_quotes_the_path(self):
        path = Path('/tmp/a "b" c/space/config.yaml')
        rendered = _server(StrictSetting(True, StrictSource.CONFIG,
                                         path)).format_error(UnrecognisedApiValue("RunStatus", "NEW"))
        quoted = rendered.split("Set strict: false in ", 1)[1].removesuffix(" and restart the MCP server" + _TAIL)
        assert json.loads(quoted) == str(path)

    @pytest.mark.parametrize("source", _SOURCES, ids=lambda s: s.name if s else "none")
    @pytest.mark.parametrize(
        ("mutation", "review", "lead", "inspect"),
        [
            (
                Mutation.MR_CREATED,
                ReviewRef(number=194200),
                "The merge request was created; do not call `put_merge_request` again.",
                "inspect MR #194200 with `get_merge_request`",
            ),
            (
                Mutation.MR_CREATED,
                ReviewRef(id="abc"),
                "The merge request was created; do not call `put_merge_request` again.",
                "call `get_merge_request` with review_id `id:abc`",
            ),
            (
                Mutation.MR_EDITED,
                ReviewRef(number=42),
                "The edit was applied; do not call `patch_merge_request` again.",
                "inspect MR #42 with `get_merge_request`",
            ),
        ],
        ids=["created-number", "created-id", "edited"],
    )
    def test_strict_mutation_hint(self, source, mutation, review, lead, inspect):
        err = MutationCompletedError(
            mutation, MutationTarget("ij", review), UnrecognisedApiValue("MRState", "NEW"), applied=["title"]
        )
        expected = f"**Error:** {err}\n\n{lead} {_restart(source, Path('/cfg/space/config.yaml'))}, then {inspect}."
        assert _server(_setting(source)).format_error(err) == expected


# Dry-run follow-up ====================================================================================================


def _timeline_with_run(server: SpaceMCP) -> None:
    server.space_client.get_merge_request_discussions = AsyncMock(
        return_value=[
            TimelineMessage(
                event_class=TimelineEventClass.MC_MESSAGE,
                text=f"Dry run started\nhttps://patronus.labs.jb.gg/robot/{_RID}",
                author=make_account(),
                created_at=make_dt(),
                attachments=(),
                thread_replies=(),
            )
        ]
    )


class TestDryRunFollowup:

    _SENTENCE = f"{_restart(StrictSource.ENV)}{_TAIL}"

    def _server(self) -> SpaceMCP:
        server = _server(_setting(StrictSource.ENV))
        server.space_client.start_safe_merge = AsyncMock(side_effect=ConnectionResetError("reset"))
        server.space_client.get_merge_request = AsyncMock()
        return server

    async def test_read_failure_after_run_id(self):
        server = self._server()
        _timeline_with_run(server)
        server.patronus_client.get_run = AsyncMock(side_effect=UnrecognisedApiValue("RunStatus", "NEW"))
        result = await server.put_patronus_dry_run("ij", "id:abc")
        assert result.endswith(
            f"However, a dry run may exist for this merge request (run `{_RID}`), but its status could not be read: "
            f"RunStatus: unrecognised value 'NEW' (strict mode). {self._SENTENCE} "
            f"Use `get_patronus_run` with run ID `{_RID}` to inspect it before starting another."
        )

    async def test_check_failure_before_run_id(self):
        server = self._server()
        server.space_client.get_merge_request_discussions = AsyncMock(
            side_effect=UnrecognisedApiValue("ReviewState", "NEW")
        )
        result = await server.put_patronus_dry_run("ij", "id:abc")
        assert result.endswith(
            "Note: the dry run may have started despite this error, but checking failed: "
            f"ReviewState: unrecognised value 'NEW' (strict mode). {self._SENTENCE} {_DRY_RUN_CHECK_HINT}"
        )

    @pytest.mark.parametrize("point", ["discussions", "get_run"])
    async def test_ordinary_failure_gets_no_strict_sentence(self, point):
        server = self._server()
        if point == "discussions":
            server.space_client.get_merge_request_discussions = AsyncMock(side_effect=ValueError("bad"))
        else:
            _timeline_with_run(server)
            server.patronus_client.get_run = AsyncMock(side_effect=ValueError("bad"))
        result = await server.put_patronus_dry_run("ij", "id:abc")
        assert "restart the MCP server" not in result
        assert "bad." in result
