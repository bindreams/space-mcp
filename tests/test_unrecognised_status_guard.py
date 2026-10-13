"""The suite refuses Patronus status values that no DTO enum defines, except in the body of an opted-in test."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

_HOOKS = (
    "pytest_configure",
    "pytest_unconfigure",
    "pytest_collection_finish",
    "pytest_runtest_setup",
    "pytest_runtest_call",
    "pytest_runtest_teardown",
    "pytest_runtest_makereport",
    "pytest_fixture_setup",
    "pytest_sessionstart",
    "pytest_sessionfinish",
)

_GUARD_IMPORT = "import tests._status_guard  # noqa: F401\n"
_HOOK_IMPORT = f"from tests.conftest import {', '.join(_HOOKS)}  # noqa: F401\n"
_INNER_CONFTEST = _GUARD_IMPORT + _HOOK_IMPORT

_MARKED = "@pytest.mark.unrecognised_api_value"


# The in-process inner run parses through the same enums, so each outer test opts in as well.
def _run(pytester, test_source: str, conftest_extra: str = "", *args: str):
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function\n")
    pytester.makeconftest(_INNER_CONFTEST + conftest_extra)
    pytester.makepyfile(test_inner=test_source)
    return pytester.runpytest_inprocess("-p", "no:dotenv", *args)


_INNER_TEST = """
import pytest
from space.models import enums

{marker}
def test_parses_new_value():
    assert enums.RunStatus("NEW_VALUE") is enums.RunStatus.UNKNOWN
"""


@pytest.mark.unrecognised_api_value
def test_unrecognised_value_without_marker_fails_the_test(pytester):
    result = _run(pytester, _INNER_TEST.format(marker=""))

    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*parsed a value Patronus does not send*RunStatus 'NEW_VALUE' (call)*"])


@pytest.mark.unrecognised_api_value
def test_unrecognised_value_with_marker_passes(pytester):
    result = _run(pytester, _INNER_TEST.format(marker=_MARKED))

    result.assert_outcomes(passed=1)


@pytest.mark.unrecognised_api_value
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


@pytest.mark.unrecognised_api_value
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

@pytest.mark.unrecognised_api_value
def test_last_item_in_scope():
    pass
"""


@pytest.mark.unrecognised_api_value
def test_guard_catches_module_scoped_fixture_setup(pytester):
    result = _run(pytester, _MODULE_FIXTURE_TEST.format(marker=""))

    assert result.parseoutcomes().get("failed", 0) + result.parseoutcomes().get("errors", 0) >= 1
    result.stdout.fnmatch_lines(["*parsed a value Patronus does not send*RunStatus 'MODULE_SETUP_VALUE' (setup)*"])


@pytest.mark.unrecognised_api_value
def test_guard_catches_session_scoped_fixture_teardown(pytester):
    result = _run(pytester, _SESSION_TEARDOWN_TEST)

    assert result.parseoutcomes().get("failed", 0) + result.parseoutcomes().get("errors", 0) >= 1
    result.stdout.fnmatch_lines([
        "*parsed a value Patronus does not send*RunStatus 'SESSION_TEARDOWN_VALUE' (teardown)*"
    ])


@pytest.mark.unrecognised_api_value
def test_marker_does_not_allow_module_fixture_setup(pytester):
    result = _run(pytester, _MODULE_FIXTURE_TEST.format(marker=_MARKED))

    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*RunStatus 'MODULE_SETUP_VALUE' (setup)*"])


@pytest.mark.unrecognised_api_value
def test_module_fixture_teardown_parse_fails_even_if_users_are_marked(pytester):
    result = _run(pytester, _MODULE_TEARDOWN_TEST.format(first_marker=_MARKED))

    assert result.ret != pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*RunStatus 'MODULE_TEARDOWN_VALUE' (teardown)*"])


@pytest.mark.unrecognised_api_value
def test_unmarked_user_of_parsing_fixture_fails(pytester):
    result = _run(pytester, _MODULE_TEARDOWN_TEST.format(first_marker=""))

    assert result.ret != pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*RunStatus 'MODULE_TEARDOWN_VALUE' (teardown)*"])


@pytest.mark.unrecognised_api_value
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


@pytest.mark.unrecognised_api_value
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


@pytest.mark.unrecognised_api_value
@pytest.mark.parametrize("xfail", ["@pytest.mark.xfail", "@pytest.mark.xfail(strict=True)"])
def test_xfail_does_not_hide_an_unmarked_parse(pytester, xfail):
    result = _run(
        pytester,
        f"""
import pytest
from space.models import enums

{xfail}
def test_parses():
    enums.RunStatus("XFAIL_VALUE")
""",
    )

    assert result.ret != pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*RunStatus 'XFAIL_VALUE' (call)*"])


@pytest.mark.unrecognised_api_value
def test_xfail_does_not_hide_a_marked_tests_fixture_parse(pytester):
    result = _run(
        pytester,
        f"""
import pytest
from space.models import enums

@pytest.fixture
def parses_on_setup():
    enums.RunStatus("XFAIL_FIXTURE_VALUE")

@pytest.mark.xfail
{_MARKED}
def test_uses_fixture(parses_on_setup):
    pass
""",
    )

    assert result.ret != pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*RunStatus 'XFAIL_FIXTURE_VALUE' (setup)*"])


def test_import_time_value_fails_the_run(pytester, monkeypatch):
    # A fresh process: the guard module is imported first, then something parses while importing.
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function\n")
    pytester.makeconftest(
        _GUARD_IMPORT + "from space.models import enums\nenums.RunStatus('IMPORT_TIME_VALUE')\n" + _HOOK_IMPORT
    )
    pytester.makepyfile("def test_nothing():\n    pass\n")

    result = pytester.runpytest_subprocess("-p", "no:dotenv")

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "RunStatus 'IMPORT_TIME_VALUE' (collection)" in result.stderr.str()


@pytest.mark.unrecognised_api_value
def test_session_fixture_teardown_after_pytest_exit_fails_the_run(pytester):
    result = _run(
        pytester,
        """
import pytest
from space.models import enums

@pytest.fixture(scope="session")
def parses_on_teardown():
    yield
    enums.RunStatus("EXIT_VALUE")

def test_exits(parses_on_teardown):
    pytest.exit("done", returncode=0)
""",
    )

    assert result.ret != pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*RunStatus 'EXIT_VALUE' (between)*"])


@pytest.mark.unrecognised_api_value
def test_fixture_requested_in_the_call_phase_is_still_a_fixture(pytester):
    result = _run(
        pytester,
        f"""
import pytest
from space.models import enums

@pytest.fixture
def parses_on_setup():
    enums.RunStatus("LATE_FIXTURE_VALUE")

{_MARKED}
def test_requests_late(request):
    request.getfixturevalue("parses_on_setup")
""",
    )

    assert result.ret != pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*RunStatus 'LATE_FIXTURE_VALUE' (setup)*"])


@pytest.mark.unrecognised_api_value
def test_teardown_error_does_not_hide_a_violation(pytester):
    result = _run(
        pytester,
        """
import pytest
from space.models import enums

@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("teardown exploded")

def test_parses_unmarked(broken_teardown):
    enums.RunStatus("HIDDEN_VALUE")
""",
    )

    assert result.ret != pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*teardown exploded*"])
    result.stdout.fnmatch_lines(["*RunStatus 'HIDDEN_VALUE' (call)*"])


@pytest.mark.unrecognised_api_value
def test_unconfigure_survives_a_guard_that_never_configured(pytester, monkeypatch):
    monkeypatch.syspath_prepend(pytester.path)
    pytester.makepyfile(
        failing_configure_plugin="""
import pytest

@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    raise pytest.UsageError("configure refused")
"""
    )

    result = _run(pytester, "def test_nothing():\n    pass\n", "", "-p", "failing_configure_plugin")

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "configure refused" in result.stderr.str()
    assert "KeyError" not in result.stderr.str() + result.stdout.str()


@pytest.mark.unrecognised_api_value
def test_between_items_report_works_without_a_terminal(pytester):
    result = _run(
        pytester,
        "def test_nothing():\n    pass\n",
        """
from space.models import enums

def pytest_runtest_logstart(nodeid, location):
    enums.RunStatus("BETWEEN_VALUE")
""",
        "-p",
        "no:terminal",
    )

    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert "RunStatus 'BETWEEN_VALUE' (between)" in result.stderr.str()
    assert "Traceback" not in result.stderr.str()


@pytest.mark.unrecognised_api_value
def test_nested_in_process_run_does_not_orphan_the_outer_state(pytester, tmp_path_factory):
    nested = tmp_path_factory.mktemp("nested")
    (nested / "conftest.py").write_text(_INNER_CONFTEST)
    (nested / "test_nested.py").write_text("def test_nested():\n    pass\n")
    result = _run(
        pytester,
        """
import pytest
from space.models import enums

def test_first():
    pass

def test_second_parses_unmarked():
    enums.RunStatus("OUTER_VALUE")
""",
        f"""
import pytest

def pytest_runtest_logfinish(nodeid, location):
    if "test_first" in nodeid:
        pytest.main([{str(nested)!r}, "-p", "no:dotenv", "-p", "no:cacheprovider"])
""",
    )

    assert result.ret != pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*RunStatus 'OUTER_VALUE' (call)*"])
    result.stdout.no_fnmatch_line("*ValueError*")


def test_value_parsed_before_the_guard_is_imported_fails_the_run(pytester, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function\n")
    pytester.makeconftest(
        "from space.models import enums\nenums.RunStatus('BEFORE_GUARD_VALUE')\n" + _GUARD_IMPORT + _HOOK_IMPORT
    )
    pytester.makepyfile("def test_nothing():\n    pass\n")

    result = pytester.runpytest_subprocess("-p", "no:dotenv")

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "RunStatus 'BEFORE_GUARD_VALUE' (collection)" in result.stderr.str()


_PROBE_IMPORTS = "import pytest\nfrom space.models import enums\n"

_CUT_SHORT_PROBES = {
    "exit-after-body-parse": (
        _PROBE_IMPORTS + """
def test_a():
    enums.RunStatus("PROBE_VALUE")
    pytest.exit("stop", returncode=0)
""",
        "",
    ),
    "exit-in-fixture-setup": (
        _PROBE_IMPORTS + """
@pytest.fixture
def f():
    enums.RunStatus("PROBE_VALUE")
    pytest.exit("stop", returncode=0)

def test_a(f):
    pass
""",
        "",
    ),
    "exit-in-sessionstart": (
        "def test_a():\n    pass\n",
        _PROBE_IMPORTS + """
class _StartProbe:
    def pytest_sessionstart(self, session):
        enums.RunStatus("PROBE_VALUE")
        pytest.exit("stop", returncode=0)

def pytest_addhooks(pluginmanager):
    pluginmanager.register(_StartProbe())
""",
    ),
    "keyboard-interrupt": (
        _PROBE_IMPORTS + """
def test_a():
    enums.RunStatus("PROBE_VALUE")
    raise KeyboardInterrupt
""",
        "",
    ),
}


@pytest.mark.unrecognised_api_value
@pytest.mark.parametrize("probe", _CUT_SHORT_PROBES)
def test_run_cut_short_still_reports_parsed_values(pytester, monkeypatch, probe):
    source, conftest_extra = _CUT_SHORT_PROBES[probe]
    if probe == "keyboard-interrupt":
        # An in-process run would re-raise the interrupt into this session.
        monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
        pytester.makeini("[pytest]\nasyncio_default_fixture_loop_scope = function\n")
        pytester.makeconftest(_INNER_CONFTEST + conftest_extra)
        pytester.makepyfile(source)
        result = pytester.runpytest_subprocess("-p", "no:dotenv")
    else:
        result = _run(pytester, source, conftest_extra)

    assert result.ret != pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*RunStatus 'PROBE_VALUE'*"])


@pytest.mark.unrecognised_api_value
def test_session_finish_check_survives_a_raising_session_teardown(pytester):
    result = _run(
        pytester,
        _PROBE_IMPORTS + """
@pytest.fixture(scope="session")
def parses_on_teardown():
    yield
    enums.RunStatus("TD_VALUE")

@pytest.fixture(scope="session")
def exits_on_teardown():
    yield
    pytest.exit("bye", returncode=0)

def test_exits(parses_on_teardown, exits_on_teardown):
    pytest.exit("stop", returncode=0)
""",
    )

    assert result.ret != pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*RunStatus 'TD_VALUE'*"])


@pytest.mark.unrecognised_api_value
def test_raising_teardown_keeps_its_exception_in_the_summary(pytester):
    result = _run(
        pytester,
        _PROBE_IMPORTS + """
@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("td boom")

def test_parses_unmarked(broken_teardown):
    enums.RunStatus("SUMMARY_VALUE")
""",
    )

    assert result.ret != pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["ERROR *test_parses_unmarked - RuntimeError: td boom"])
    result.stdout.fnmatch_lines(["*RunStatus 'SUMMARY_VALUE' (call)*"])


@pytest.mark.unrecognised_api_value
def test_skipping_teardown_does_not_print_a_raw_tuple(pytester):
    result = _run(
        pytester,
        _PROBE_IMPORTS + """
@pytest.fixture
def skipping_teardown():
    yield
    pytest.skip("td skip")

def test_parses_unmarked(skipping_teardown):
    enums.RunStatus("SKIP_VALUE")
""",
    )

    assert result.ret != pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*td skip*", "*RunStatus 'SKIP_VALUE' (call)*"])
    assert not re.search(r"\('.*', \d+, ", result.stdout.str())
