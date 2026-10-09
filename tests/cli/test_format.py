from __future__ import annotations

from space.cli.format import _PATRONUS_STATUS_COLORS, _STATUS_COLORS
from space.cli.run import _CHECK_SYMBOLS, _WATCH_BUCKETS
from space.models import CheckStatus, RunStatus


def test_every_check_status_is_covered_by_buckets_symbols_and_colours():
    known = set(CheckStatus) - {CheckStatus.UNKNOWN}
    assert known <= {status for status, _ in _WATCH_BUCKETS}
    assert known <= set(_CHECK_SYMBOLS)
    assert known <= set(_PATRONUS_STATUS_COLORS)


def test_every_run_status_is_covered_by_colours():
    assert set(RunStatus) - {RunStatus.UNKNOWN} <= set(_PATRONUS_STATUS_COLORS)


def test_string_colours_derive_from_the_enum_colours():
    for status, color in _PATRONUS_STATUS_COLORS.items():
        assert _STATUS_COLORS[status.value] == color


def test_canceling_and_queued_colours():
    assert _STATUS_COLORS["CANCELING"] == "yellow"
    assert _STATUS_COLORS["QUEUED"] == "white"
