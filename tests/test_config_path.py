import json
import logging
from pathlib import PureWindowsPath

import pytest

from space.config import config_dir, config_path


def _win(path) -> PureWindowsPath:
    assert path is not None
    return PureWindowsPath(str(path))


# POSIX ----------------------------------------------------------------------------------------------------------------


def test_posix_xdg_absolute_wins():
    env = {"XDG_CONFIG_HOME": "/x/cfg", "HOME": "/home/u"}
    assert str(config_dir(env, windows=False)) == "/x/cfg/space"
    assert str(config_path(env, windows=False)) == "/x/cfg/space/config.yaml"


def test_posix_default_is_home_dot_config():
    env = {"HOME": "/home/u"}
    assert str(config_path(env, windows=False)) == "/home/u/.config/space/config.yaml"


@pytest.mark.parametrize("xdg", ["", "rel/cfg"])
def test_posix_bad_xdg_is_ignored_and_logged(xdg, caplog):
    caplog.set_level(logging.DEBUG, logger="space.config")
    env = {"XDG_CONFIG_HOME": xdg, "HOME": "/home/u"}
    assert str(config_dir(env, windows=False)) == "/home/u/.config/space"
    assert json.dumps(xdg, ensure_ascii=True) in caplog.text
    assert "XDG_CONFIG_HOME" in caplog.text


def test_posix_xdg_logged_json_escaped(caplog):
    caplog.set_level(logging.DEBUG, logger="space.config")
    config_dir({"XDG_CONFIG_HOME": "rel\u202e\n", "HOME": "/h"}, windows=False)
    assert '"rel\\u202e\\n"' in caplog.text


@pytest.mark.parametrize("home", [None, "", "rel"])
def test_posix_no_usable_home_is_none_and_logged(home, caplog):
    caplog.set_level(logging.DEBUG, logger="space.config")
    env = {} if home is None else {"HOME": home}
    assert config_dir(env, windows=False) is None
    assert config_path(env, windows=False) is None
    assert "no usable home" in caplog.text


def test_posix_bad_xdg_and_bad_home_is_none():
    assert config_dir({"XDG_CONFIG_HOME": "rel", "HOME": "rel"}, windows=False) is None


def test_resolved_path_logged_at_debug(caplog):
    caplog.set_level(logging.DEBUG, logger="space.config")
    config_dir({"HOME": "/home/u"}, windows=False)
    records = [r for r in caplog.records if r.name == "space.config"]
    assert records
    assert all(r.levelno == logging.DEBUG for r in records)
    assert "/home/u/.config/space" in caplog.text


# Windows --------------------------------------------------------------------------------------------------------------


def test_windows_userprofile():
    env = {"USERPROFILE": r"C:\Users\u"}
    assert _win(config_dir(env, windows=True)) == PureWindowsPath(r"C:\Users\u\.config\space")
    assert _win(config_path(env, windows=True)) == PureWindowsPath(r"C:\Users\u\.config\space\config.yaml")


def test_windows_homedrive_homepath_when_userprofile_unset():
    env = {"HOMEDRIVE": "C:", "HOMEPATH": r"\Users\u"}
    assert _win(config_dir(env, windows=True)) == PureWindowsPath(r"C:\Users\u\.config\space")


@pytest.mark.parametrize("userprofile", ["", "rel", r"\cfg"])
def test_windows_bad_userprofile_falls_through(userprofile):
    env = {"USERPROFILE": userprofile, "HOMEDRIVE": "D:", "HOMEPATH": r"\h"}
    assert _win(config_dir(env, windows=True)) == PureWindowsPath(r"D:\h\.config\space")


def test_windows_absolute_xdg_wins():
    env = {"XDG_CONFIG_HOME": r"C:\cfg", "USERPROFILE": r"C:\Users\u"}
    assert _win(config_dir(env, windows=True)) == PureWindowsPath(r"C:\cfg\space")


def test_windows_driveless_rooted_xdg_ignored(caplog):
    caplog.set_level(logging.DEBUG, logger="space.config")
    env = {"XDG_CONFIG_HOME": r"\cfg", "USERPROFILE": r"C:\Users\u"}
    assert _win(config_dir(env, windows=True)) == PureWindowsPath(r"C:\Users\u\.config\space")
    assert "XDG_CONFIG_HOME" in caplog.text


def test_windows_driveless_rooted_userprofile_and_no_fallback_is_none():
    assert config_dir({"USERPROFILE": r"\cfg"}, windows=True) is None


def test_windows_none_usable():
    assert config_dir({}, windows=True) is None
    assert config_path({"HOMEDRIVE": "C:"}, windows=True) is None


def test_windows_ignores_posix_home():
    assert config_dir({"HOME": "/home/u"}, windows=True) is None


# Windows absoluteness -------------------------------------------------------------------------------------------------

_NOT_ABSOLUTE = [r"\\server", "//", "\\\\?\\", r"\cfg"]


@pytest.mark.parametrize("value", _NOT_ABSOLUTE)
def test_windows_xdg_not_drive_and_root_is_ignored(value):
    env = {"XDG_CONFIG_HOME": value, "USERPROFILE": r"C:\Users\u"}
    assert _win(config_dir(env, windows=True)) == PureWindowsPath(r"C:\Users\u\.config\space")


@pytest.mark.parametrize("value", _NOT_ABSOLUTE)
def test_windows_userprofile_not_drive_and_root_is_ignored(value):
    assert config_dir({"USERPROFILE": value}, windows=True) is None
    env = {"USERPROFILE": value, "HOMEDRIVE": "D:", "HOMEPATH": r"\h"}
    assert _win(config_dir(env, windows=True)) == PureWindowsPath(r"D:\h\.config\space")


@pytest.mark.parametrize("value", [r"C:\cfg", r"\\server\share\cfg"])
def test_windows_drive_and_root_is_used(value):
    assert _win(config_dir({"XDG_CONFIG_HOME": value}, windows=True)) == PureWindowsPath(value) / "space"
    assert _win(config_dir({"USERPROFILE": value}, windows=True)) == PureWindowsPath(value) / ".config" / "space"
