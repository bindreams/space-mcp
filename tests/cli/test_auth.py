"""Tests for auth login CLI flow, docker login, and git credential approve."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from space.client import validate_token

from .conftest import run_cli

# auth login CLI =======================================================================================================


class TestAuthLogin:

    @patch("space.cli.auth._confirm_git_login", return_value=False)
    @patch("space.cli.auth._confirm_docker_login", return_value=False)
    @patch("space.cli.auth.validate_token")
    @patch("space.auth._keyring_set", return_value=True)
    @patch("space.auth._file_delete")
    def test_valid_token_shows_user(self, mock_fdel, mock_kset, mock_validate, mock_docker, mock_git):
        mock_validate.return_value = {
            "kind": "user",
            "username": "azhukova",
            "emails": [{"email": "anna@jetbrains.com"}],
        }
        result = run_cli("auth", "login", "--token", "good-tok")
        assert result.exit_code == 0
        assert "azhukova" in result.output
        assert "anna@jetbrains.com" in result.output

    @patch("space.cli.auth.validate_token")
    def test_invalid_token_rejected(self, mock_validate):
        mock_validate.side_effect = httpx.HTTPStatusError(
            "401",
            request=MagicMock(),
            response=MagicMock(status_code=401),
        )
        result = run_cli("auth", "login", "--token", "bad-tok")
        assert result.exit_code != 0
        assert "Invalid token" in result.output

    @patch("space.cli.auth.validate_token")
    def test_connection_error(self, mock_validate):
        mock_validate.side_effect = httpx.ConnectError("Connection refused")
        result = run_cli("auth", "login", "--token", "tok")
        assert result.exit_code != 0
        assert "connect" in result.output.lower()

    @patch("space.cli.auth._confirm_git_login", return_value=False)
    @patch("space.cli.auth._confirm_docker_login", return_value=True)
    @patch("space.cli.auth._docker_login", new_callable=AsyncMock)
    @patch("space.cli.auth.validate_token")
    @patch("space.auth._keyring_set", return_value=True)
    @patch("space.auth._file_delete")
    def test_docker_accepted(self, mock_fdel, mock_kset, mock_validate, mock_docker, mock_confirm, mock_git):
        mock_validate.return_value = {"kind": "user", "username": "u", "emails": [{"email": "a@b.com"}]}
        result = run_cli("auth", "login", "--token", "tok")
        assert result.exit_code == 0
        mock_docker.assert_called_once_with("a@b.com", "tok")

    @patch("space.cli.auth._confirm_git_login", return_value=False)
    @patch("space.cli.auth._confirm_docker_login", return_value=False)
    @patch("space.cli.auth.validate_token")
    @patch("space.auth._keyring_set", return_value=True)
    @patch("space.auth._file_delete")
    def test_docker_declined(self, mock_fdel, mock_kset, mock_validate, mock_confirm, mock_git):
        mock_validate.return_value = {"kind": "user", "username": "u", "emails": [{"email": "a@b.com"}]}
        result = run_cli("auth", "login", "--token", "tok")
        assert result.exit_code == 0
        assert "Docker authenticated" not in result.output

    @patch("space.cli.auth._confirm_git_login", return_value=False)
    @patch("space.cli.auth._confirm_docker_login", return_value=False)
    @patch("space.cli.auth.validate_token")
    @patch("space.auth._keyring_set", return_value=True)
    @patch("space.auth._file_delete")
    def test_no_email_skips_docker_prompt(self, mock_fdel, mock_kset, mock_validate, mock_confirm, mock_git):
        mock_validate.return_value = {"kind": "user", "username": "u", "emails": []}
        result = run_cli("auth", "login", "--token", "tok")
        assert result.exit_code == 0
        mock_confirm.assert_not_called()

    @patch("space.cli.auth._confirm_git_login", return_value=True)
    @patch("space.cli.auth._git_credential_approve", new_callable=AsyncMock)
    @patch("space.cli.auth._confirm_docker_login", return_value=False)
    @patch("space.cli.auth.validate_token")
    @patch("space.auth._keyring_set", return_value=True)
    @patch("space.auth._file_delete")
    def test_git_accepted(self, mock_fdel, mock_kset, mock_validate, mock_docker, mock_git_approve, mock_git_confirm):
        mock_validate.return_value = {"kind": "user", "username": "u", "emails": [{"email": "a@b.com"}]}
        result = run_cli("auth", "login", "--token", "tok")
        assert result.exit_code == 0
        mock_git_approve.assert_called_once_with("a@b.com", "tok")

    @patch("space.cli.auth._confirm_git_login", return_value=False)
    @patch("space.cli.auth._git_credential_approve", new_callable=AsyncMock)
    @patch("space.cli.auth._confirm_docker_login", return_value=False)
    @patch("space.cli.auth.validate_token")
    @patch("space.auth._keyring_set", return_value=True)
    @patch("space.auth._file_delete")
    def test_git_declined(self, mock_fdel, mock_kset, mock_validate, mock_docker, mock_git_approve, mock_git_confirm):
        mock_validate.return_value = {"kind": "user", "username": "u", "emails": [{"email": "a@b.com"}]}
        result = run_cli("auth", "login", "--token", "tok")
        assert result.exit_code == 0
        mock_git_approve.assert_not_called()

    @patch("space.cli.auth._confirm_git_login", return_value=True)
    @patch("space.cli.auth._confirm_docker_login", return_value=False)
    @patch("space.cli.auth.validate_token")
    @patch("space.auth._keyring_set", return_value=True)
    @patch("space.auth._file_delete")
    def test_no_email_skips_git_prompt(self, mock_fdel, mock_kset, mock_validate, mock_docker, mock_git_confirm):
        mock_validate.return_value = {"kind": "user", "username": "u", "emails": []}
        result = run_cli("auth", "login", "--token", "tok")
        assert result.exit_code == 0
        mock_git_confirm.assert_not_called()

    # App token tests --------------------------------------------------------------------------------------------------

    @patch("space.cli.auth._confirm_git_login")
    @patch("space.cli.auth._confirm_docker_login")
    @patch("space.cli.auth.validate_token")
    @patch("space.auth._keyring_set", return_value=True)
    @patch("space.auth._file_delete")
    def test_app_token_shows_app_name(self, mock_fdel, mock_kset, mock_validate, mock_docker, mock_git):
        mock_validate.return_value = {"kind": "app", "name": "my-app"}
        result = run_cli("auth", "login", "--token", "app-tok")
        assert result.exit_code == 0
        assert "application" in result.output.lower()
        assert "my-app" in result.output

    @patch("space.cli.auth._confirm_git_login")
    @patch("space.cli.auth._confirm_docker_login")
    @patch("space.cli.auth.validate_token")
    @patch("space.auth._keyring_set", return_value=True)
    @patch("space.auth._file_delete")
    def test_app_token_skips_git_docker_prompts(self, mock_fdel, mock_kset, mock_validate, mock_docker, mock_git):
        mock_validate.return_value = {"kind": "app", "name": "my-app"}
        result = run_cli("auth", "login", "--token", "app-tok")
        assert result.exit_code == 0
        mock_git.assert_not_called()
        mock_docker.assert_not_called()

    @patch("space.cli.auth.validate_token")
    def test_invalid_app_token_rejected(self, mock_validate):
        mock_validate.side_effect = httpx.HTTPStatusError(
            "403",
            request=MagicMock(),
            response=MagicMock(status_code=403),
        )
        result = run_cli("auth", "login", "--token", "bad-app-tok")
        assert result.exit_code != 0
        assert "Invalid token" in result.output


# auth status CLI ======================================================================================================


class TestAuthStatus:

    @patch("space.cli.auth.validate_token")
    @patch("space.cli.auth.resolve_token_source", return_value="env")
    @patch("space.auth.resolve_token", return_value="tok")
    def test_status_shows_app_identity(self, mock_resolve, mock_source, mock_validate):
        mock_validate.return_value = {"kind": "app", "name": "my-app"}
        result = run_cli("auth", "status")
        assert result.exit_code == 0
        assert "application" in result.output.lower()
        assert "my-app" in result.output

    @patch("space.cli.auth.validate_token")
    @patch("space.cli.auth.resolve_token_source", return_value="env")
    @patch("space.auth.resolve_token", return_value="tok")
    def test_status_shows_user_identity(self, mock_resolve, mock_source, mock_validate):
        mock_validate.return_value = {
            "kind": "user",
            "username": "azhukova",
            "name": {"firstName": "Anna", "lastName": "Zhukova"},
            "emails": [{"email": "a@b.com"}],
        }
        result = run_cli("auth", "status")
        assert result.exit_code == 0
        assert "Anna Zhukova" in result.output


# _docker_login() ======================================================================================================


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


# _git_credential_approve() ============================================================================================


class TestGitCredentialApprove:

    @patch("shutil.which", return_value=None)
    async def test_git_not_installed(self, mock_which):
        from space.cli.auth import _git_credential_approve
        await _git_credential_approve("user", "tok")
        # Should not raise, just warn

    @patch("shutil.which", return_value="/usr/bin/git")
    @patch("asyncio.create_subprocess_exec")
    async def test_git_credential_success(self, mock_exec, mock_which):
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"")
        proc.returncode = 0
        mock_exec.return_value = proc

        from space.cli.auth import _git_credential_approve
        await _git_credential_approve("anna@jetbrains.com", "my-token")

        call_args = mock_exec.call_args[0]
        assert call_args == ("/usr/bin/git", "credential", "approve")
        credential_input = proc.communicate.call_args[1]["input"].decode()
        assert "protocol=https" in credential_input
        assert "host=git.jetbrains.team" in credential_input
        assert "username=anna@jetbrains.com" in credential_input
        assert "password=my-token" in credential_input

    @patch("shutil.which", return_value="/usr/bin/git")
    @patch("asyncio.create_subprocess_exec")
    async def test_git_credential_failure(self, mock_exec, mock_which):
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"error: unable to store\n")
        proc.returncode = 1
        mock_exec.return_value = proc

        from space.cli.auth import _git_credential_approve
        await _git_credential_approve("user", "tok")
        # Should not raise, just warn

    async def test_git_credential_roundtrip(self):
        """Approve then fill: git must return the stored credentials."""
        import shutil
        git_path = shutil.which("git")
        if git_path is None:
            pytest.skip("git not installed")

        host = "test-roundtrip.invalid"
        username = "testuser@example.com"
        token = "test-token-abc123"

        with tempfile.TemporaryDirectory() as tmpdir:
            cred_file = Path(tmpdir) / "credentials"
            env = _make_isolated_git_env(cred_file)

            # Approve (store)
            approve_input = ("protocol=https\n"
                             f"host={host}\n"
                             f"username={username}\n"
                             f"password={token}\n"
                             "\n")
            proc = await asyncio.create_subprocess_exec(
                git_path,
                "credential",
                "approve",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            await proc.communicate(input=approve_input.encode())
            assert proc.returncode == 0

            # Fill (retrieve)
            fill_input = f"protocol=https\nhost={host}\n\n"
            proc = await asyncio.create_subprocess_exec(
                git_path,
                "credential",
                "fill",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, _ = await proc.communicate(input=fill_input.encode())
            assert proc.returncode == 0
            output = stdout.decode()
            assert f"username={username}" in output
            assert f"password={token}" in output


# Git credential clone integration test ================================================================================


async def _git(
    *args: str,
    env: dict[str, str],
    cwd: str | Path | None = None,
) -> tuple[int, str, str]:
    """Run git with custom env, return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=cwd,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(), stderr.decode()


def _make_isolated_git_env(cred_file: Path) -> dict[str, str]:
    """Build an env dict that isolates git from system credential helpers.

    Uses credential.helper=store backed by a temp file so nothing leaks
    to/from the user's real keychain.
    """
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "credential.helper"
    env["GIT_CONFIG_VALUE_0"] = f"store --file={cred_file}"
    return env


async def _credential_approve(
    env: dict[str, str],
    host: str,
    username: str,
    password: str,
) -> int:
    """Run git credential approve with the given fields. Returns exit code."""
    credential_input = ("protocol=https\n"
                        f"host={host}\n"
                        f"username={username}\n"
                        f"password={password}\n"
                        "\n")
    proc = await asyncio.create_subprocess_exec(
        "git",
        "credential",
        "approve",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    await proc.communicate(input=credential_input.encode())
    return proc.returncode


CLONE_REPO = "https://git.jetbrains.team/space-mcp/test.git"


@pytest.mark.e2e
class TestGitCredentialCloneIntegration:
    """Integration tests that clone a real Space repo via git credential approve.

    Requires SPACE_TOKEN (via .env or environment). Uses an isolated git
    credential store (temp file) so the user's real keychain is never touched.
    Tests marked user_token require SPACE_USER_TOKEN (personal access token with email).
    """

    @pytest.fixture
    def space_token(self):
        token = os.environ.get("SPACE_TOKEN")
        if not token:
            pytest.fail("SPACE_TOKEN not set — required for integration tests")
        return token

    @pytest.fixture
    def user_token(self):
        """Personal access token with email. Set SPACE_USER_TOKEN env var."""
        token = os.environ.get("SPACE_USER_TOKEN")
        if not token:
            pytest.fail("SPACE_USER_TOKEN not set — required for git credential tests with email")
        return token

    @pytest.fixture
    def space_email(self, user_token):
        """Fetch the user's email from Space API."""

        async def _fetch():
            profile = await validate_token(user_token)
            emails = [e["email"] for e in profile.get("emails", []) if "email" in e]
            if not emails:
                pytest.fail("SPACE_USER_TOKEN has no email configured")
            return emails[0]

        return asyncio.run(_fetch())

    @pytest.mark.user_token
    async def test_clone_with_email_credential(self, user_token, space_email):
        """Storing credentials with email username allows cloning."""
        git_path = shutil.which("git")
        if git_path is None:
            pytest.skip("git not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            cred_file = Path(tmpdir) / "credentials"
            clone_dir = Path(tmpdir) / "repo"
            env = _make_isolated_git_env(cred_file)

            # Store credentials using email (the fix)
            rc = await _credential_approve(
                env,
                "git.jetbrains.team",
                space_email,
                user_token,
            )
            assert rc == 0

            # Clone should succeed using stored credentials
            rc, stdout, stderr = await _git(
                "clone",
                "--depth=1",
                CLONE_REPO,
                str(clone_dir),
                env=env,
            )
            assert rc == 0, f"Clone failed: {stderr}"
            assert (clone_dir / ".git").is_dir()

    async def test_clone_with_empty_username_fails(self, space_token):
        """Storing credentials with empty username fails to authenticate.

        This is the regression test: the original implementation used an empty
        username, which credential helpers silently ignore or fail to match.
        """
        git_path = shutil.which("git")
        if git_path is None:
            pytest.skip("git not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            cred_file = Path(tmpdir) / "credentials"
            clone_dir = Path(tmpdir) / "repo"
            env = _make_isolated_git_env(cred_file)

            # Store credentials with empty username (the old bug)
            await _credential_approve(
                env,
                "git.jetbrains.team",
                "",
                space_token,
            )

            # Clone should fail — credential helper won't match
            rc, stdout, stderr = await _git(
                "clone",
                "--depth=1",
                CLONE_REPO,
                str(clone_dir),
                env=env,
            )
            assert rc != 0, ("Clone unexpectedly succeeded with empty username — "
                             "this test expected it to fail")
