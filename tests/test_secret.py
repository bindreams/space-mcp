"""Tokens handed to tests must never appear in pytest's failure output."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from .e2e_helpers import Secret, authenticated_url, require_env_token

TOKEN = "s3cr3t-token-value"


def test_repr_is_masked():
    assert repr(Secret(TOKEN)) == "'***'"


def test_value_is_unchanged_for_use():
    token = Secret(TOKEN)
    assert token == TOKEN
    assert str(token) == TOKEN
    assert f"Bearer {token}" == f"Bearer {TOKEN}"


def test_require_env_token_masks(monkeypatch):
    monkeypatch.setenv("SPACE_TOKEN", TOKEN)
    token = require_env_token("SPACE_TOKEN")
    assert token == TOKEN
    assert TOKEN not in repr(token)


def test_require_env_token_fails_when_unset(monkeypatch):
    monkeypatch.delenv("SPACE_TOKEN", raising=False)
    with pytest.raises(pytest.fail.Exception, match="SPACE_TOKEN not set"):
        require_env_token("SPACE_TOKEN")


def test_space_token_fixture_is_masked(monkeypatch, request):
    monkeypatch.setenv("SPACE_TOKEN", TOKEN)
    token = request.getfixturevalue("space_token")
    assert token == TOKEN
    assert TOKEN not in repr(token)


def test_authenticated_url_is_masked():
    url = authenticated_url("https://git.jetbrains.team/space-mcp/test.git", Secret(TOKEN))
    assert TOKEN in str(url)
    assert TOKEN not in repr(url)


def test_failing_test_traceback_does_not_print_token(tmp_path):
    # pytest prints every frame's arguments in a long traceback; a Secret argument must render masked.
    # The token reaches the inner test through the environment, since pytest also prints source lines.
    (tmp_path / "test_leak.py").write_text(
        textwrap.dedent(
            """
            import os

            from tests.e2e_helpers import Secret, authenticated_url

            def helper(token, auth_url):
                assert False

            def test_leak():
                token = Secret(os.environ["LEAK_TOKEN"])
                helper(token, authenticated_url("https://git.jetbrains.team/p/r.git", token))
            """
        )
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest",
         str(tmp_path / "test_leak.py"), "-p", "no:cacheprovider", "--tb=long"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
        env={**os.environ, "LEAK_TOKEN": TOKEN},
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "token = '***'" in result.stdout
    assert TOKEN not in result.stdout + result.stderr
