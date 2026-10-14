"""End-to-end smoke test of the CLI's strict-mode wiring against live Space (no Patronus).

Requires SPACE_TOKEN environment variable to be set (via .env or export).
"""

import pytest

from space.models import enums
from tests.cli.conftest import run_cli
from tests.conftest import TEST_RW_PROJECT, TEST_RW_REPO_NAME


@pytest.mark.e2e
def test_cli_strict_flag_against_live_space(space_token, monkeypatch):
    enums.set_strict(False)
    monkeypatch.delenv("SPACE_STRICT")

    result = run_cli("--strict", "-P", TEST_RW_PROJECT, "-R", TEST_RW_REPO_NAME, "mr", "list", "-s", "all")

    assert result.exit_code == 0, result.output
    assert enums.is_strict() is True
