"""Tests for token resolution and credential management."""

import json
from unittest.mock import patch

import pytest

import space.auth as auth_mod
from space.auth import (
    resolve_token, resolve_token_source, load_stored_token,
    store_token, delete_token,
)


# Token resolution =====


class TestResolveToken:
    @patch("space.auth._keyring_get", return_value=None)
    @patch("space.auth.load_stored_token", return_value="stored-token")
    def test_env_var_takes_priority(self, mock_file, mock_kr, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "env-token")
        assert resolve_token() == "env-token"

    @patch("space.auth._keyring_get", return_value="keyring-token")
    @patch("space.auth.load_stored_token", return_value=None)
    def test_keyring_before_file(self, mock_file, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        assert resolve_token() == "keyring-token"

    @patch("space.auth._keyring_get", return_value=None)
    @patch("space.auth.load_stored_token", return_value="file-token")
    def test_falls_back_to_file(self, mock_file, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        assert resolve_token() == "file-token"

    @patch("space.auth._keyring_get", return_value=None)
    @patch("space.auth.load_stored_token", return_value=None)
    def test_returns_none_when_nothing_available(self, mock_file, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        assert resolve_token() is None


class TestResolveTokenSource:
    @patch("space.auth._keyring_get", return_value=None)
    def test_env(self, mock_kr, monkeypatch):
        monkeypatch.setenv("SPACE_TOKEN", "tok")
        assert resolve_token_source() == "env"

    @patch("space.auth._keyring_get", return_value="tok")
    def test_keyring(self, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        assert resolve_token_source() == "keyring"

    @patch("space.auth._keyring_get", return_value=None)
    @patch("space.auth.load_stored_token", return_value="tok")
    def test_config(self, mock_file, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        assert resolve_token_source() == "config"

    @patch("space.auth._keyring_get", return_value=None)
    @patch("space.auth.load_stored_token", return_value=None)
    def test_none(self, mock_file, mock_kr, monkeypatch):
        monkeypatch.delenv("SPACE_TOKEN", raising=False)
        assert resolve_token_source() is None


# File-based storage =====


class TestLoadStoredToken:
    def test_loads_token_from_file(self, tmp_path, monkeypatch):
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text(json.dumps({"https://jetbrains.team": {"token": "file-token"}}))
        monkeypatch.setattr(auth_mod, "_CREDENTIALS_FILE", creds_file)
        assert load_stored_token() == "file-token"

    def test_returns_none_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(auth_mod, "_CREDENTIALS_FILE", tmp_path / "nonexistent.json")
        assert load_stored_token() is None

    def test_returns_none_on_invalid_json(self, tmp_path, monkeypatch):
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text("not json")
        monkeypatch.setattr(auth_mod, "_CREDENTIALS_FILE", creds_file)
        assert load_stored_token() is None


# store_token =====


class TestStoreToken:
    @patch("space.auth._keyring_set", return_value=True)
    @patch("space.auth._file_delete")
    def test_stores_in_keyring_by_default(self, mock_fdel, mock_kset):
        used_keyring, desc = store_token("my-token")
        assert used_keyring is True
        assert "keyring" in desc
        mock_kset.assert_called_once_with("my-token")

    @patch("space.auth._keyring_set", return_value=True)
    @patch("space.auth._file_delete")
    def test_keyring_success_cleans_file(self, mock_fdel, mock_kset):
        store_token("my-token")
        mock_fdel.assert_called_once()

    @patch("space.auth._keyring_set", return_value=False)
    @patch("space.auth._file_store")
    def test_falls_back_to_file_on_keyring_failure(self, mock_fstore, mock_kset):
        used_keyring, desc = store_token("my-token")
        assert used_keyring is False
        mock_fstore.assert_called_once_with("my-token")

    @patch("space.auth._keyring_set", return_value=True)
    @patch("space.auth._file_store")
    def test_insecure_skips_keyring(self, mock_fstore, mock_kset):
        used_keyring, desc = store_token("my-token", insecure=True)
        assert used_keyring is False
        mock_kset.assert_not_called()
        mock_fstore.assert_called_once()

    def test_file_store_creates_file(self, tmp_path, monkeypatch):
        creds_file = tmp_path / "subdir" / "credentials.json"
        monkeypatch.setattr(auth_mod, "_CREDENTIALS_FILE", creds_file)
        store_token("tok123", insecure=True)
        assert creds_file.exists()
        creds = json.loads(creds_file.read_text())
        assert creds["https://jetbrains.team"]["token"] == "tok123"
        assert oct(creds_file.stat().st_mode & 0o777) == "0o600"


# delete_token =====


class TestDeleteToken:
    @patch("space.auth._keyring_get", return_value="tok")
    @patch("space.auth._keyring_delete", return_value=True)
    @patch("space.auth.load_stored_token", return_value=None)
    def test_deletes_from_keyring(self, mock_file, mock_kdel, mock_kget):
        delete_token()
        mock_kdel.assert_called_once()

    @patch("space.auth._keyring_get", return_value=None)
    @patch("space.auth.load_stored_token", return_value="tok")
    @patch("space.auth._file_delete", return_value=True)
    def test_deletes_from_file(self, mock_fdel, mock_file, mock_kget):
        delete_token()
        mock_fdel.assert_called_once()

    @patch("space.auth._keyring_get", return_value=None)
    @patch("space.auth.load_stored_token", return_value=None)
    def test_raises_when_not_found(self, mock_file, mock_kget):
        with pytest.raises(RuntimeError, match="No credentials found"):
            delete_token()

    @patch("space.auth._keyring_get", return_value="tok")
    @patch("space.auth._keyring_delete", return_value=False)
    @patch("space.auth.load_stored_token", return_value=None)
    def test_raises_on_keyring_delete_failure(self, mock_file, mock_kdel, mock_kget):
        with pytest.raises(RuntimeError, match="Failed to remove"):
            delete_token()

    @patch("space.auth._keyring_get", return_value=None)
    @patch("space.auth.load_stored_token", return_value="tok")
    @patch("space.auth._file_delete", return_value=False)
    def test_raises_on_file_delete_failure(self, mock_fdel, mock_file, mock_kget):
        with pytest.raises(RuntimeError, match="Failed to remove"):
            delete_token()

    @patch("space.auth._keyring_get", return_value="tok")
    @patch("space.auth._keyring_delete", return_value=True)
    @patch("space.auth.load_stored_token", return_value="tok")
    @patch("space.auth._file_delete", return_value=True)
    def test_deletes_from_both_when_present(self, mock_fdel, mock_file, mock_kdel, mock_kget):
        delete_token()
        mock_kdel.assert_called_once()
        mock_fdel.assert_called_once()
