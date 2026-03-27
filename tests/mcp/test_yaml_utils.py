"""Tests for YAML serialization utility."""

from __future__ import annotations

from ruamel.yaml import YAML

from space.mcp.yaml_utils import dump_yaml


def _load(text: str):
    """Parse YAML text using ruamel.yaml (YAML 1.2 safe loader)."""
    return YAML(typ="safe").load(text)


class TestDumpYaml:

    def test_simple_dict(self):
        result = dump_yaml({"key": "value"})
        assert _load(result) == {"key": "value"}

    def test_none_values_stripped(self):
        data = {"a": 1, "b": None, "c": "hello"}
        parsed = _load(dump_yaml(data))
        assert parsed == {"a": 1, "c": "hello"}
        assert "b" not in parsed

    def test_none_in_nested_dict_stripped(self):
        data = {"outer": {"keep": 1, "drop": None}}
        parsed = _load(dump_yaml(data))
        assert parsed == {"outer": {"keep": 1}}

    def test_none_elements_in_list_filtered(self):
        data = {"items": [1, None, 3]}
        parsed = _load(dump_yaml(data))
        assert parsed == {"items": [1, 3]}

    def test_empty_string_preserved(self):
        data = {"name": ""}
        parsed = _load(dump_yaml(data))
        assert parsed == {"name": ""}

    def test_empty_list_preserved(self):
        data = {"items": []}
        parsed = _load(dump_yaml(data))
        assert parsed == {"items": []}

    def test_block_style(self):
        result = dump_yaml({"a": {"b": "c"}})
        assert "{" not in result
        assert "[" not in result

    def test_round_trip(self):
        data = {"top": {"nested": [{"x": 1}, {"y": 2}]}}
        result = dump_yaml(data)
        assert _load(result) == data

    def test_timestamp_string_survives_round_trip(self):
        data = {"started-at": "2026-01-16T11:00:00+03:00"}
        parsed = _load(dump_yaml(data))
        assert isinstance(parsed["started-at"], str)
        assert parsed["started-at"] == "2026-01-16T11:00:00+03:00"

    def test_time_string_survives_round_trip(self):
        data = {"time": "10:00"}
        parsed = _load(dump_yaml(data))
        assert isinstance(parsed["time"], str)
        assert parsed["time"] == "10:00"

    def test_list_indentation(self):
        result = dump_yaml({"items": [{"a": 1}]})
        lines = result.strip().split("\n")
        assert lines[1].startswith("  - ")

    def test_nested_none_in_list_of_dicts(self):
        data = {"items": [{"a": 1, "b": None}, {"c": None, "d": 2}]}
        parsed = _load(dump_yaml(data))
        assert parsed == {"items": [{"a": 1}, {"d": 2}]}
