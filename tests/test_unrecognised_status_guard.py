"""The suite refuses Patronus status values that no DTO enum defines, unless a test opts in."""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]

_INNER_CONFTEST = "from tests.conftest import _unrecognised_patronus_guard, pytest_runtest_call  # noqa: F401\n"

_INNER_TEST = """
import pytest
from space.models import enums

{marker}
def test_parses_new_value():
    assert enums.RunStatus("NEW_VALUE") is enums.RunStatus.UNKNOWN
"""


# The in-process inner run logs through the same logger, so the outer test opts in as well.
@pytest.mark.unrecognised_patronus_status
def test_unrecognised_value_without_marker_fails_the_test(pytester):
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function\n")
    pytester.makeconftest(_INNER_CONFTEST)
    pytester.makepyfile(_INNER_TEST.format(marker=""))

    result = pytester.runpytest_inprocess()

    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*parsed a value Patronus does not send*unrecognised Patronus RunStatus value*"])


@pytest.mark.unrecognised_patronus_status
def test_unrecognised_value_with_marker_passes(pytester):
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function\n")
    pytester.makeconftest(_INNER_CONFTEST)
    pytester.makepyfile(_INNER_TEST.format(marker="@pytest.mark.unrecognised_patronus_status"))

    result = pytester.runpytest_inprocess()

    result.assert_outcomes(passed=1)
