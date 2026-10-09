"""The suite refuses Patronus status values that no DTO enum defines, unless a test opts in."""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]

_INNER_CONFTEST = (
    "from tests.conftest import pytest_configure, pytest_unconfigure, pytest_runtest_setup, "
    "pytest_runtest_teardown  # noqa: F401\n"
)

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

    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*parsed a value Patronus does not send*unrecognised Patronus RunStatus value*"])


@pytest.mark.unrecognised_patronus_status
def test_unrecognised_value_with_marker_passes(pytester):
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function\n")
    pytester.makeconftest(_INNER_CONFTEST)
    pytester.makepyfile(_INNER_TEST.format(marker="@pytest.mark.unrecognised_patronus_status"))

    result = pytester.runpytest_inprocess()

    result.assert_outcomes(passed=1)


_MODULE_FIXTURE_TEST = """
import pytest
from space.models import enums

@pytest.fixture(scope="module")
def parses_on_setup():
    enums.RunStatus("MODULE_SETUP_VALUE")
    yield

{marker}
def test_uses_fixture(parses_on_setup):
    pass
"""

_SESSION_TEARDOWN_TEST = """
import pytest
from space.models import enums

@pytest.fixture(scope="session")
def parses_on_teardown():
    yield
    enums.RunStatus("SESSION_TEARDOWN_VALUE")

def test_uses_fixture(parses_on_teardown):
    pass
"""


@pytest.mark.unrecognised_patronus_status
def test_guard_catches_module_scoped_fixture_setup(pytester):
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function\n")
    pytester.makeconftest(_INNER_CONFTEST)
    pytester.makepyfile(_MODULE_FIXTURE_TEST.format(marker=""))

    result = pytester.runpytest_inprocess()

    assert result.parseoutcomes().get("failed", 0) + result.parseoutcomes().get("errors", 0) >= 1
    result.stdout.fnmatch_lines(["*parsed a value Patronus does not send*MODULE_SETUP_VALUE*"])


@pytest.mark.unrecognised_patronus_status
def test_guard_catches_session_scoped_fixture_teardown(pytester):
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function\n")
    pytester.makeconftest(_INNER_CONFTEST)
    pytester.makepyfile(_SESSION_TEARDOWN_TEST)

    result = pytester.runpytest_inprocess()

    assert result.parseoutcomes().get("failed", 0) + result.parseoutcomes().get("errors", 0) >= 1
    result.stdout.fnmatch_lines(["*parsed a value Patronus does not send*SESSION_TEARDOWN_VALUE*"])


@pytest.mark.unrecognised_patronus_status
def test_guard_marker_still_opts_out_for_module_fixture(pytester):
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function\n")
    pytester.makeconftest(_INNER_CONFTEST)
    pytester.makepyfile(_MODULE_FIXTURE_TEST.format(marker="@pytest.mark.unrecognised_patronus_status"))

    result = pytester.runpytest_inprocess()

    result.assert_outcomes(passed=1)
