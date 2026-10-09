"""The suite refuses Patronus status values that no DTO enum defines, except in the body of an opted-in test."""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]

_HOOKS = (
    "pytest_configure",
    "pytest_unconfigure",
    "pytest_collection_finish",
    "pytest_runtest_setup",
    "pytest_runtest_call",
    "pytest_runtest_teardown",
    "pytest_sessionfinish",
)

_INNER_CONFTEST = f"from tests.conftest import {', '.join(_HOOKS)}  # noqa: F401\n"

_MARKED = "@pytest.mark.unrecognised_patronus_status"


# The in-process inner run parses through the same enums, so each outer test opts in as well.
def _run(pytester, test_source: str, conftest_extra: str = ""):
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function\n")
    pytester.makeconftest(_INNER_CONFTEST + conftest_extra)
    pytester.makepyfile(test_source)
    return pytester.runpytest_inprocess("-p", "no:dotenv")


_INNER_TEST = """
import pytest
from space.models import enums

{marker}
def test_parses_new_value():
    assert enums.RunStatus("NEW_VALUE") is enums.RunStatus.UNKNOWN
"""


@pytest.mark.unrecognised_patronus_status
def test_unrecognised_value_without_marker_fails_the_test(pytester):
    result = _run(pytester, _INNER_TEST.format(marker=""))

    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*parsed a value Patronus does not send*RunStatus 'NEW_VALUE' (call)*"])


@pytest.mark.unrecognised_patronus_status
def test_unrecognised_value_with_marker_passes(pytester):
    result = _run(pytester, _INNER_TEST.format(marker=_MARKED))

    result.assert_outcomes(passed=1)


@pytest.mark.unrecognised_patronus_status
def test_collection_time_value_fails_the_run(pytester):
    result = _run(
        pytester,
        f"""
import pytest
from space.models import enums

enums.RunStatus("MODULE_LEVEL_VALUE")

@pytest.mark.parametrize("status", [enums.CheckStatus("PARAMETRIZE_VALUE")])
{_MARKED}
def test_uses_param(status):
    pass
""",
    )

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*RunStatus 'MODULE_LEVEL_VALUE' (collection)*"])
    result.stderr.fnmatch_lines(["*CheckStatus 'PARAMETRIZE_VALUE' (collection)*"])


@pytest.mark.unrecognised_patronus_status
def test_guard_ignores_logger_level(pytester):
    result = _run(
        pytester,
        """
import logging
from space.models import enums

def test_raises_logger_level_then_parses():
    logging.getLogger("space.models").setLevel(logging.INFO)
    enums.RunStatus("LEVEL_VALUE")
""",
    )

    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*parsed a value Patronus does not send*RunStatus 'LEVEL_VALUE' (call)*"])


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

_MODULE_TEARDOWN_TEST = """
import pytest
from space.models import enums

@pytest.fixture(scope="module")
def parses_on_teardown():
    yield
    enums.RunStatus("MODULE_TEARDOWN_VALUE")

{first_marker}
def test_first_user(parses_on_teardown):
    pass

@pytest.mark.unrecognised_patronus_status
def test_last_item_in_scope():
    pass
"""


@pytest.mark.unrecognised_patronus_status
def test_guard_catches_module_scoped_fixture_setup(pytester):
    result = _run(pytester, _MODULE_FIXTURE_TEST.format(marker=""))

    assert result.parseoutcomes().get("failed", 0) + result.parseoutcomes().get("errors", 0) >= 1
    result.stdout.fnmatch_lines(["*parsed a value Patronus does not send*RunStatus 'MODULE_SETUP_VALUE' (setup)*"])


@pytest.mark.unrecognised_patronus_status
def test_guard_catches_session_scoped_fixture_teardown(pytester):
    result = _run(pytester, _SESSION_TEARDOWN_TEST)

    assert result.parseoutcomes().get("failed", 0) + result.parseoutcomes().get("errors", 0) >= 1
    result.stdout.fnmatch_lines([
        "*parsed a value Patronus does not send*RunStatus 'SESSION_TEARDOWN_VALUE' (teardown)*"
    ])


@pytest.mark.unrecognised_patronus_status
def test_marker_does_not_allow_module_fixture_setup(pytester):
    result = _run(pytester, _MODULE_FIXTURE_TEST.format(marker=_MARKED))

    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*RunStatus 'MODULE_SETUP_VALUE' (setup)*"])


@pytest.mark.unrecognised_patronus_status
def test_module_fixture_teardown_parse_fails_even_if_users_are_marked(pytester):
    result = _run(pytester, _MODULE_TEARDOWN_TEST.format(first_marker=_MARKED))

    assert result.ret != pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*RunStatus 'MODULE_TEARDOWN_VALUE' (teardown)*"])


@pytest.mark.unrecognised_patronus_status
def test_unmarked_user_of_parsing_fixture_fails(pytester):
    result = _run(pytester, _MODULE_TEARDOWN_TEST.format(first_marker=""))

    assert result.ret != pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*RunStatus 'MODULE_TEARDOWN_VALUE' (teardown)*"])


@pytest.mark.unrecognised_patronus_status
def test_marker_allows_call_phase_only(pytester):
    result = _run(
        pytester,
        f"""
import pytest
from space.models import enums

@pytest.fixture
def parses_on_setup():
    enums.RunStatus("FIXTURE_VALUE")

{_MARKED}
def test_marked_body_parses():
    enums.RunStatus("BODY_VALUE")

{_MARKED}
def test_marked_fixture_parses(parses_on_setup):
    pass
""",
    )

    result.assert_outcomes(passed=2, errors=1)
    result.stdout.fnmatch_lines(["*ERROR at teardown of test_marked_fixture_parses*"])
    result.stdout.no_fnmatch_line("*teardown of test_marked_body_parses*")
    result.stdout.fnmatch_lines(["*RunStatus 'FIXTURE_VALUE' (setup)*"])


@pytest.mark.unrecognised_patronus_status
def test_value_parsed_between_items_fails_the_session(pytester):
    result = _run(
        pytester,
        "def test_nothing():\n    pass\n",
        conftest_extra="""
from space.models import enums

def pytest_runtest_logstart(nodeid, location):
    enums.RunStatus("BETWEEN_VALUE")
""",
    )

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.stdout.fnmatch_lines(["*RunStatus 'BETWEEN_VALUE' (between)*"])
