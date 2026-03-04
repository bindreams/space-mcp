"""Tests for token validation and auth login flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from space.__main__ import main
from space.client import validate_token


def _run(*args):
    runner = CliRunner()
    return runner.invoke(main, list(args), catch_exceptions=False)


# validate_token() =============================================================


class TestValidateToken:
    async def test_valid_token_returns_profile(self, httpx_mock):
        httpx_mock.add_response(json={
            "username": "azhukova",
            "emails": [{"email": "anna@jetbrains.com"}],
        })
        result = await validate_token("good-token")
        assert result["username"] == "azhukova"
        assert result["emails"][0]["email"] == "anna@jetbrains.com"

    async def test_requests_correct_url_and_fields(self, httpx_mock):
        httpx_mock.add_response(json={"username": "x", "emails": []})
        await validate_token("tok")
        request = httpx_mock.get_request()
        assert "team-directory/profiles/me" in str(request.url)
        assert "username" in str(request.url)
        assert "emails" in str(request.url)

    async def test_invalid_token_401(self, httpx_mock):
        httpx_mock.add_response(status_code=401)
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await validate_token("bad-token")
        assert exc_info.value.response.status_code == 401

    async def test_invalid_token_403(self, httpx_mock):
        httpx_mock.add_response(status_code=403)
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await validate_token("bad-token")
        assert exc_info.value.response.status_code == 403

    async def test_server_error(self, httpx_mock):
        httpx_mock.add_response(status_code=500)
        with pytest.raises(httpx.HTTPStatusError):
            await validate_token("tok")


# auth login CLI ===============================================================


class TestAuthLogin:
    @patch("space.cli.auth._confirm_docker_login", return_value=False)
    @patch("space.cli.auth.validate_token")
    @patch("space.context._keyring_set", return_value=True)
    @patch("space.context._file_delete")
    def test_valid_token_shows_user(self, mock_fdel, mock_kset, mock_validate, mock_docker):
        mock_validate.return_value = {
            "username": "azhukova",
            "emails": [{"email": "anna@jetbrains.com"}],
        }
        result = _run("auth", "login", "--token", "good-tok")
        assert result.exit_code == 0
        assert "azhukova" in result.output
        assert "anna@jetbrains.com" in result.output

    @patch("space.cli.auth.validate_token")
    def test_invalid_token_rejected(self, mock_validate):
        mock_validate.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=MagicMock(status_code=401),
        )
        result = _run("auth", "login", "--token", "bad-tok")
        assert result.exit_code != 0
        assert "Invalid token" in result.output

    @patch("space.cli.auth.validate_token")
    def test_connection_error(self, mock_validate):
        mock_validate.side_effect = httpx.ConnectError("Connection refused")
        result = _run("auth", "login", "--token", "tok")
        assert result.exit_code != 0
        assert "connect" in result.output.lower()

    @patch("space.cli.auth._confirm_docker_login", return_value=True)
    @patch("space.cli.auth._docker_login", new_callable=AsyncMock)
    @patch("space.cli.auth.validate_token")
    @patch("space.context._keyring_set", return_value=True)
    @patch("space.context._file_delete")
    def test_docker_accepted(self, mock_fdel, mock_kset, mock_validate, mock_docker, mock_confirm):
        mock_validate.return_value = {"username": "u", "emails": [{"email": "a@b.com"}]}
        result = _run("auth", "login", "--token", "tok")
        assert result.exit_code == 0
        mock_docker.assert_called_once_with("a@b.com", "tok")

    @patch("space.cli.auth._confirm_docker_login", return_value=False)
    @patch("space.cli.auth.validate_token")
    @patch("space.context._keyring_set", return_value=True)
    @patch("space.context._file_delete")
    def test_docker_declined(self, mock_fdel, mock_kset, mock_validate, mock_confirm):
        mock_validate.return_value = {"username": "u", "emails": [{"email": "a@b.com"}]}
        result = _run("auth", "login", "--token", "tok")
        assert result.exit_code == 0
        assert "Docker authenticated" not in result.output

    @patch("space.cli.auth._confirm_docker_login", return_value=False)
    @patch("space.cli.auth.validate_token")
    @patch("space.context._keyring_set", return_value=True)
    @patch("space.context._file_delete")
    def test_no_email_skips_docker_prompt(self, mock_fdel, mock_kset, mock_validate, mock_confirm):
        mock_validate.return_value = {"username": "u", "emails": []}
        result = _run("auth", "login", "--token", "tok")
        assert result.exit_code == 0
        mock_confirm.assert_not_called()


# _docker_login() ==============================================================


class TestDockerLogin:
    @patch("shutil.which", return_value=None)
    async def test_docker_not_installed(self, mock_which):
        from space.cli.auth import _docker_login
        await _docker_login("a@b.com", "tok")
        # Should not raise, just warn

    @patch("shutil.which", return_value="/usr/bin/docker")
    @patch("asyncio.create_subprocess_exec")
    async def test_docker_login_success(self, mock_exec, mock_which):
        proc = AsyncMock()
        proc.communicate.return_value = (b"Login Succeeded\n", b"")
        proc.returncode = 0
        mock_exec.return_value = proc

        from space.cli.auth import _docker_login
        await _docker_login("a@b.com", "my-token")

        call_args = mock_exec.call_args[0]
        assert "registry.jetbrains.team" in call_args
        assert "--password-stdin" in call_args
        assert "--username" in call_args
        proc.communicate.assert_called_once_with(input=b"my-token")

    @patch("shutil.which", return_value="/usr/bin/docker")
    @patch("asyncio.create_subprocess_exec")
    async def test_docker_login_failure(self, mock_exec, mock_which):
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"Error from daemon\n")
        proc.returncode = 1
        mock_exec.return_value = proc

        from space.cli.auth import _docker_login
        await _docker_login("a@b.com", "tok")
        # Should not raise, just warn
