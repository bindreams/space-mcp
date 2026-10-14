"""Strict mode in the CLI: `--strict/--no-strict`, `SPACE_STRICT` and the config file, resolved lazily."""

from __future__ import annotations

import json
import os
from pathlib import Path

import click
import pytest

from space.cli.app import CliState
from space.models import enums
from tests.sample_responses import wire_check, wire_run

from .conftest import RUN_ID, patronus_url, run_cli

_ENV = {"SPACE_TOKEN": "test"}
_STRICT_ERROR = "Error: RunStatus: unrecognised value 'NEW_STATUS' (strict mode)"
_RERUN = "Run as `space --no-strict <command>` to treat unrecognised values as UNKNOWN."
_BAD_ENV = 'Error: SPACE_STRICT: expected 1, true, yes, on, 0, false, no or off, got "maybe"'


def _config(text: str) -> Path:
    path = Path(os.environ["XDG_CONFIG_HOME"]) / "space" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _run_view(httpx_mock, status: str, *, failing: bool) -> None:
    """`run view` responses; the siblings of a failing get_run may never be requested."""
    base = patronus_url(f"/app/rest/v1/robots/{RUN_ID}")
    httpx_mock.add_response(url=base, json=wire_run(status))
    httpx_mock.add_response(
        url=f"{base}/teamcity-checks",
        json={"robotId": RUN_ID, "teamCityChecks": [wire_check("SUCCESS")]},
        is_optional=failing,
    )
    httpx_mock.add_response(url=f"{base}/problems", json={"problems": []}, is_optional=failing)


class TestEnable:

    @pytest.mark.raises_unrecognised_api_value
    @pytest.mark.parametrize(
        ("args", "env", "config"),
        [
            (["--strict"], {"SPACE_STRICT": "0"}, None),
            ([], {"SPACE_STRICT": "1"}, None),
            ([], None, "strict: true\n"),
            ([], {"SPACE_STRICT": "1"}, "strict: false\n"),
        ],
        ids=["flag", "env", "config", "env-beats-config"],
    )
    def test_strict_is_turned_on(self, httpx_mock, test_accounts, monkeypatch, args, env, config):
        enums.set_strict(False)
        if env is None:
            monkeypatch.delenv("SPACE_STRICT")
        if config is not None:
            _config(config)
        _run_view(httpx_mock, "NEW_STATUS", failing=True)

        result = run_cli(*args, "run", "view", RUN_ID, env={**_ENV, **(env or {})})

        assert result.exit_code == 1
        assert f"{_STRICT_ERROR}\n{_RERUN}" in result.output


class TestDisable:

    @pytest.mark.parametrize(
        ("args", "env", "config"),
        [
            (["--no-strict"], {"SPACE_STRICT": "1"}, None),
            ([], {"SPACE_STRICT": "0"}, None),
            ([], {"SPACE_STRICT": "0"}, "strict: true\n"),
            ([], None, None),
        ],
        ids=["flag-beats-env", "env", "env-beats-config", "default"],
    )
    def test_strict_is_turned_off(self, httpx_mock, test_accounts, monkeypatch, args, env, config):
        if env is None:
            monkeypatch.delenv("SPACE_STRICT")
        if config is not None:
            _config(config)
        _run_view(httpx_mock, "NEW_STATUS", failing=False)

        result = run_cli(*args, "run", "view", RUN_ID, env={**_ENV, **(env or {})})

        assert result.exit_code == 0, result.output
        assert "UNKNOWN — DRY_RUN" in result.output


class TestBadSettings:

    @pytest.mark.parametrize("args", [[], ["--no-strict"]], ids=["no-flag", "flag"])
    def test_bad_env_value_is_a_click_error(self, args):
        result = run_cli(*args, "run", "view", RUN_ID, env={**_ENV, "SPACE_STRICT": "maybe"})

        assert result.exit_code == 1
        assert _BAD_ENV in result.output
        assert isinstance(result.exception, SystemExit)

    def test_broken_config_is_a_click_error_naming_the_file(self, monkeypatch):
        monkeypatch.delenv("SPACE_STRICT")
        path = _config("strict: maybe\n")

        result = run_cli("run", "view", RUN_ID, env=_ENV)

        assert result.exit_code == 1
        assert f"Error: {json.dumps(str(path))}: strict: expected a boolean, got str" in result.output

    @pytest.mark.parametrize(("args", "env"), [(["--no-strict"], {}), ([], {"SPACE_STRICT": "0"})], ids=["flag", "env"])
    def test_broken_config_does_not_block_no_strict_or_env(self, httpx_mock, test_accounts, monkeypatch, args, env):
        monkeypatch.delenv("SPACE_STRICT")
        _config("strict: maybe\n")
        _run_view(httpx_mock, "RUNNING", failing=False)

        result = run_cli(*args, "run", "view", RUN_ID, env={**_ENV, **env})

        assert result.exit_code == 0, result.output

    def test_commands_without_an_api_client_ignore_a_broken_config(self, httpx_mock, monkeypatch):
        monkeypatch.delenv("SPACE_STRICT")
        _config("strict: maybe\n")
        httpx_mock.add_response(url="https://jetbrains.team/api/http/x", json={"ok": True})

        assert run_cli("mr", "list", "--help").exit_code == 0
        assert run_cli("api", "/api/http/x", env=_ENV).exit_code == 0


class TestCliStateResolution:

    def test_outside_async_command_is_a_click_error(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test")
        monkeypatch.setenv("SPACE_STRICT", "maybe")
        with pytest.raises(click.ClickException) as info:
            CliState(None, None, None).space_client()
        assert info.value.message == _BAD_ENV.removeprefix("Error: ")

    def test_failed_resolution_raises_again(self, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "test")
        monkeypatch.setenv("SPACE_STRICT", "maybe")
        state = CliState(None, None, None)
        with pytest.raises(click.ClickException):
            state.space_client()
        with pytest.raises(click.ClickException):
            state.patronus_client()

    @pytest.mark.unrecognised_api_value
    def test_resolves_once(self, monkeypatch):
        import space.strict

        def no_config(path):
            raise AssertionError("the config file must not be read")

        monkeypatch.setattr(space.strict, "load_config", no_config)
        monkeypatch.setenv("SPACE_TOKEN", "test")
        monkeypatch.setenv("SPACE_STRICT", "1")
        state = CliState(None, None, None)
        state.space_client()
        assert enums.is_strict() is True

        monkeypatch.setenv("SPACE_STRICT", "0")
        state.patronus_client()
        state.space_client()
        assert enums.is_strict() is True


@pytest.mark.raises_unrecognised_api_value
def test_strict_failure_before_a_mutation_gets_the_rerun_hint(httpx_mock):
    httpx_mock.add_response(
        method="GET", json={"id": "abc", "number": 42, "title": "T", "state": "NEW_STATE", "createdAt": 1736937000000}
    )

    result = run_cli("mr", "edit", "42", "-t", "T", env={**_ENV, "SPACE_PROJECT": "ij", "SPACE_REPO": "ultimate"})

    assert result.exit_code == 1
    assert f"Error: MRState: unrecognised value 'NEW_STATE' (strict mode)\n{_RERUN}" in result.output
    assert httpx_mock.get_requests(method="PATCH") == []


def test_cli_resolves_before_parsing(httpx_mock, test_accounts):
    enums._set_strict_state(None)
    _run_view(httpx_mock, "NEW_STATUS", failing=False)

    result = run_cli("--no-strict", "run", "view", RUN_ID, env=_ENV)

    assert result.exit_code == 0, result.output
