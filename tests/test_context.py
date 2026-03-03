"""Tests for git context inference and token resolution."""

import json
from unittest.mock import patch, MagicMock

import pytest

import space.context as ctx_mod
from space.context import (
    GitContext, _parse_remote_url, detect_git_context, resolve_context,
    resolve_token, resolve_token_source, load_stored_token,
    store_token, delete_token,
)


class TestParseRemoteUrl:
    def test_https_url(self):
        result = _parse_remote_url("https://git.jetbrains.team/ij/ultimate.git")
        assert result == ("ij", "ultimate")

    def test_https_url_no_git_suffix(self):
        result = _parse_remote_url("https://git.jetbrains.team/ij/ultimate")
        assert result == ("ij", "ultimate")

    def test_ssh_url(self):
        result = _parse_remote_url("ssh://git@git.jetbrains.team/ij/ultimate")
        assert result == ("ij", "ultimate")

    def test_ssh_url_with_git_suffix(self):
        result = _parse_remote_url("ssh://git@git.jetbrains.team/ij/ultimate.git")
        assert result == ("ij", "ultimate")

    def test_scp_style_url(self):
        result = _parse_remote_url("git@git.jetbrains.team:ij/ultimate.git")
        assert result == ("ij", "ultimate")

    def test_non_space_url_returns_none(self):
        result = _parse_remote_url("https://github.com/user/repo.git")
        assert result is None

    def test_empty_string_returns_none(self):
        result = _parse_remote_url("")
        assert result is None


class TestDetectGitContext:
    @patch("space.context._run_git")
    def test_full_context(self, mock_git):
        def side_effect(*args):
            if args == ("symbolic-ref", "--short", "HEAD"):
                return "azhukova/fix-auth"
            if args == ("remote", "get-url", "origin"):
                return "https://git.jetbrains.team/ij/ultimate.git"
            return None

        mock_git.side_effect = side_effect
        ctx = detect_git_context()
        assert ctx.project == "ij"
        assert ctx.repo == "ultimate"
        assert ctx.branch == "azhukova/fix-auth"

    @patch("space.context._run_git")
    def test_no_git_repo(self, mock_git):
        mock_git.return_value = None
        ctx = detect_git_context()
        assert ctx.project is None
        assert ctx.repo is None
        assert ctx.branch is None

    @patch("space.context._run_git")
    def test_non_space_remote(self, mock_git):
        def side_effect(*args):
            if args == ("symbolic-ref", "--short", "HEAD"):
                return "main"
            if args == ("remote", "get-url", "origin"):
                return "https://github.com/user/repo.git"
            return None

        mock_git.side_effect = side_effect
        ctx = detect_git_context()
        assert ctx.project is None
        assert ctx.repo is None
        assert ctx.branch == "main"


class TestResolveContext:
    @patch("space.context.detect_git_context")
    def test_explicit_args_override_git(self, mock_detect):
        mock_detect.return_value = GitContext(project="git-proj", repo="git-repo", branch="git-branch")
        ctx = resolve_context(project="explicit-proj", repo="explicit-repo")
        assert ctx.project == "explicit-proj"
        assert ctx.repo == "explicit-repo"
        assert ctx.branch == "git-branch"  # branch from git since not overridden

    @patch("space.context.detect_git_context")
    def test_env_vars_override_git(self, mock_detect, monkeypatch):
        mock_detect.return_value = GitContext(project="git-proj", repo="git-repo", branch="git-branch")
        monkeypatch.setenv("SPACE_PROJECT", "env-proj")
        monkeypatch.setenv("SPACE_REPO", "env-repo")
        ctx = resolve_context()
        assert ctx.project == "env-proj"
        assert ctx.repo == "env-repo"

    @patch("space.context.detect_git_context")
    def test_explicit_args_override_env(self, mock_detect, monkeypatch):
        mock_detect.return_value = GitContext()
        monkeypatch.setenv("SPACE_PROJECT", "env-proj")
        ctx = resolve_context(project="explicit-proj")
        assert ctx.project == "explicit-proj"

    @patch("space.context.detect_git_context")
    def test_falls_through_to_none(self, mock_detect):
        mock_detect.return_value = GitContext()
        ctx = resolve_context()
        assert ctx.project is None
        assert ctx.repo is None
        assert ctx.branch is None


# Token resolution =============================================================


class TestResolveToken:
    @patch("space.context._keyring_get", return_value=None)
    @patch("space.context.load_stored_token", return_value="stored-token")
    def test_env_var_takes_priority(self, mock_file, mock_kr, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "env-token")
        assert resolve_token() == "env-token"

    @patch("space.context._keyring_get", return_value="keyring-token")
    @patch("space.context.load_stored_token", return_value=None)
    def test_keyring_before_file(self, mock_file, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        assert resolve_token() == "keyring-token"

    @patch("space.context._keyring_get", return_value=None)
    @patch("space.context.load_stored_token", return_value="file-token")
    def test_falls_back_to_file(self, mock_file, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        assert resolve_token() == "file-token"

    @patch("space.context._keyring_get", return_value=None)
    @patch("space.context.load_stored_token", return_value=None)
    def test_returns_none_when_nothing_available(self, mock_file, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        assert resolve_token() is None


class TestResolveTokenSource:
    @patch("space.context._keyring_get", return_value=None)
    def test_env(self, mock_kr, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "tok")
        assert resolve_token_source() == "env"

    @patch("space.context._keyring_get", return_value="tok")
    def test_keyring(self, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        assert resolve_token_source() == "keyring"

    @patch("space.context._keyring_get", return_value=None)
    @patch("space.context.load_stored_token", return_value="tok")
    def test_config(self, mock_file, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        assert resolve_token_source() == "config"

    @patch("space.context._keyring_get", return_value=None)
    @patch("space.context.load_stored_token", return_value=None)
    def test_none(self, mock_file, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        assert resolve_token_source() is None


# File-based storage ===========================================================


class TestLoadStoredToken:
    def test_loads_token_from_file(self, tmp_path, monkeypatch):
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text(json.dumps({"https://jetbrains.team": {"token": "file-token"}}))
        monkeypatch.setattr(ctx_mod, "_CREDENTIALS_FILE", creds_file)
        assert load_stored_token() == "file-token"

    def test_returns_none_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ctx_mod, "_CREDENTIALS_FILE", tmp_path / "nonexistent.json")
        assert load_stored_token() is None

    def test_returns_none_on_invalid_json(self, tmp_path, monkeypatch):
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text("not json")
        monkeypatch.setattr(ctx_mod, "_CREDENTIALS_FILE", creds_file)
        assert load_stored_token() is None


# store_token ==================================================================


class TestStoreToken:
    @patch("space.context._keyring_set", return_value=True)
    @patch("space.context._file_delete")
    def test_stores_in_keyring_by_default(self, mock_fdel, mock_kset):
        used_keyring, desc = store_token("https://jetbrains.team", "my-token")
        assert used_keyring is True
        assert "keyring" in desc
        mock_kset.assert_called_once_with("https://jetbrains.team", "my-token")

    @patch("space.context._keyring_set", return_value=True)
    @patch("space.context._file_delete")
    def test_keyring_success_cleans_file(self, mock_fdel, mock_kset):
        store_token("https://jetbrains.team", "my-token")
        mock_fdel.assert_called_once_with("https://jetbrains.team")

    @patch("space.context._keyring_set", return_value=False)
    @patch("space.context._file_store")
    def test_falls_back_to_file_on_keyring_failure(self, mock_fstore, mock_kset):
        used_keyring, desc = store_token("https://jetbrains.team", "my-token")
        assert used_keyring is False
        mock_fstore.assert_called_once_with("https://jetbrains.team", "my-token")

    @patch("space.context._keyring_set", return_value=True)
    @patch("space.context._file_store")
    def test_insecure_skips_keyring(self, mock_fstore, mock_kset):
        used_keyring, desc = store_token("https://jetbrains.team", "my-token", insecure=True)
        assert used_keyring is False
        mock_kset.assert_not_called()
        mock_fstore.assert_called_once()

    def test_file_store_creates_file(self, tmp_path, monkeypatch):
        creds_file = tmp_path / "subdir" / "credentials.json"
        monkeypatch.setattr(ctx_mod, "_CREDENTIALS_FILE", creds_file)
        store_token("https://test.space", "tok123", insecure=True)
        assert creds_file.exists()
        creds = json.loads(creds_file.read_text())
        assert creds["https://test.space"]["token"] == "tok123"
        assert oct(creds_file.stat().st_mode & 0o777) == "0o600"


# delete_token =================================================================


class TestDeleteToken:
    @patch("space.context._keyring_get", return_value="tok")
    @patch("space.context._keyring_delete", return_value=True)
    @patch("space.context.load_stored_token", return_value=None)
    def test_deletes_from_keyring(self, mock_file, mock_kdel, mock_kget):
        delete_token("https://jetbrains.team")
        mock_kdel.assert_called_once_with("https://jetbrains.team")

    @patch("space.context._keyring_get", return_value=None)
    @patch("space.context.load_stored_token", return_value="tok")
    @patch("space.context._file_delete", return_value=True)
    def test_deletes_from_file(self, mock_fdel, mock_file, mock_kget):
        delete_token("https://jetbrains.team")
        mock_fdel.assert_called_once_with("https://jetbrains.team")

    @patch("space.context._keyring_get", return_value=None)
    @patch("space.context.load_stored_token", return_value=None)
    def test_raises_when_not_found(self, mock_file, mock_kget):
        with pytest.raises(RuntimeError, match="No credentials found"):
            delete_token("https://jetbrains.team")

    @patch("space.context._keyring_get", return_value="tok")
    @patch("space.context._keyring_delete", return_value=False)
    @patch("space.context.load_stored_token", return_value=None)
    def test_raises_on_keyring_delete_failure(self, mock_file, mock_kdel, mock_kget):
        with pytest.raises(RuntimeError, match="Failed to remove"):
            delete_token("https://jetbrains.team")

    @patch("space.context._keyring_get", return_value=None)
    @patch("space.context.load_stored_token", return_value="tok")
    @patch("space.context._file_delete", return_value=False)
    def test_raises_on_file_delete_failure(self, mock_fdel, mock_file, mock_kget):
        with pytest.raises(RuntimeError, match="Failed to remove"):
            delete_token("https://jetbrains.team")

    @patch("space.context._keyring_get", return_value="tok")
    @patch("space.context._keyring_delete", return_value=True)
    @patch("space.context.load_stored_token", return_value="tok")
    @patch("space.context._file_delete", return_value=True)
    def test_deletes_from_both_when_present(self, mock_fdel, mock_file, mock_kdel, mock_kget):
        delete_token("https://jetbrains.team")
        mock_kdel.assert_called_once()
        mock_fdel.assert_called_once()
