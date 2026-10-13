"""Debug logging of the loader."""

import json
import logging
from pathlib import Path

import pytest

from space.config import load_config

from .helpers import write


def _load_logged(path: Path, caplog) -> str:
    caplog.set_level(logging.DEBUG, logger="space.config")
    load_config(path)
    return "\n".join(r.getMessage() for r in caplog.records if r.name == "space.config")


def test_log_missing(tmp_path, caplog):
    path = tmp_path / "absent.yaml"
    text = _load_logged(path, caplog)
    assert json.dumps(str(path), ensure_ascii=True) in text
    assert "missing" in text


@pytest.mark.parametrize("content", ["", "# comment\n"])
def test_log_empty(tmp_path, caplog, content):
    path = write(tmp_path, content)
    text = _load_logged(path, caplog)
    assert json.dumps(str(path), ensure_ascii=True) in text
    assert "empty" in text


def test_log_loaded(tmp_path, caplog):
    path = write(tmp_path, "strict: true\n")
    text = _load_logged(path, caplog)
    assert json.dumps(str(path), ensure_ascii=True) in text
    assert "loaded" in text
