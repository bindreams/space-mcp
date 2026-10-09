"""Tests for CLI status styling."""

from __future__ import annotations

import pytest

from space.cli.format import _STATUS_COLORS
from space.models import CheckStatus, RunStatus


@pytest.mark.parametrize("enum", [RunStatus, CheckStatus])
def test_status_colors_cover_every_wire_value(enum):
    missing = [s.value for s in enum if s.value != "UNKNOWN" and s.value not in _STATUS_COLORS]
    assert missing == []
    assert _STATUS_COLORS["CANCELING"] == "yellow"
    for name in ("CANCELED", "QUEUED", "SKIPPED"):
        assert _STATUS_COLORS[name] == "white"
