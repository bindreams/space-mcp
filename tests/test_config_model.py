"""Tests for the Config value, default trust and trust suggestions."""

import dataclasses
import io
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType

import pytest
from ruamel.yaml import YAML

from space.config import DEFAULT_TRUSTED_ENDPOINTS, Config, ConfigValueError, load_config

JB = "https://jetbrains.team"
PATRONUS = "https://patronus.labs.jb.gg"
HUGE = int("f" * 3600, 16)  # repr() of this raises ValueError (int/str digit limit)

# Construction ---------------------------------------------------------------------------------------------------------


def test_default_config_constructs():
    config = Config()
    assert config.strict is None
    assert dict(config.trusted_endpoint_overrides) == {}
    assert config.source is None


def test_raw_key_normalised_and_empty_revokes():
    config = Config(trusted_endpoint_overrides={"https://JetBrains.team/": ()})
    assert dict(config.trusted_endpoint_overrides) == {JB: ()}
    assert config.trusted_patronus_origins(JB) == ()


def test_str_value_is_one_origin():
    config = Config(trusted_endpoint_overrides={JB: "https://Example.com:8443/"})
    assert config.trusted_endpoint_overrides[JB] == ("https://example.com:8443", )


def test_list_items_deduplicated_after_normalisation():
    config = Config(trusted_endpoint_overrides={JB: ["https://B.com", "https://a.com", "https://b.com/"]})
    assert config.trusted_endpoint_overrides[JB] == ("https://b.com", "https://a.com")


def test_normalise_equal_keys_rejected_naming_both():
    with pytest.raises(ConfigValueError) as info:
        Config(trusted_endpoint_overrides={"https://A.com": (), "https://a.com/": ()})
    assert info.value.key_path == 'patronus-trusted-endpoints."https://a.com/"'
    assert '"https://A.com"' in str(info.value)
    assert '"https://a.com/"' in str(info.value)


@pytest.mark.parametrize(
    ("raw", "key_path"),
    [
        ({JB: None}, f'patronus-trusted-endpoints."{JB}"'),
        ({JB: 5}, f'patronus-trusted-endpoints."{JB}"'),
        ({JB: {"a": "b"}}, f'patronus-trusted-endpoints."{JB}"'),
        ({1: ()}, "patronus-trusted-endpoints.<int key>"),
        ({None: ()}, "patronus-trusted-endpoints.<NoneType key>"),
        ({HUGE: ()}, "patronus-trusted-endpoints.<int key>"),
        ({JB: ["https://a.com", HUGE]}, f'patronus-trusted-endpoints."{JB}".[1]'),
        ({JB: HUGE}, f'patronus-trusted-endpoints."{JB}"'),
        ({JB: ["https://a.com", None]}, f'patronus-trusted-endpoints."{JB}".[1]'),
        ({JB: ["https://a.com", 3]}, f'patronus-trusted-endpoints."{JB}".[1]'),
        ({JB: ("http://a.com", )}, f'patronus-trusted-endpoints."{JB}".[0]'),
        ({"http://x.com": ()}, 'patronus-trusted-endpoints."http://x.com"'),
        ({JB: "not an origin"}, f'patronus-trusted-endpoints."{JB}"'),
        ({"https://é.com": ()}, 'patronus-trusted-endpoints."https://\\u00e9.com"'),
    ],
)
def test_invalid_override_key_paths(raw, key_path):
    with pytest.raises(ConfigValueError) as info:
        Config(trusted_endpoint_overrides=raw)
    assert info.value.key_path == key_path
    assert str(info.value).startswith(f"{key_path}: ")


def test_huge_int_is_named_by_type_without_crashing():
    with pytest.raises(ConfigValueError, match="int") as info:
        Config(trusted_endpoint_overrides={JB: [HUGE]})
    assert "got int" in str(info.value)
    with pytest.raises(ConfigValueError) as info:
        Config(trusted_endpoint_overrides={HUGE: ()})
    assert info.value.key_path == "patronus-trusted-endpoints.<int key>"


def test_invalid_origin_reason_includes_normaliser_message():
    with pytest.raises(ConfigValueError) as info:
        Config(trusted_endpoint_overrides={JB: "http://a.com"})
    assert '"http://a.com"' in str(info.value)


def test_non_mapping_overrides_rejected():
    with pytest.raises(ConfigValueError) as info:
        Config(trusted_endpoint_overrides=[JB])  # ty: ignore[invalid-argument-type]  # deliberately wrong type
    assert info.value.key_path == "patronus-trusted-endpoints"


@pytest.mark.parametrize("strict", ["false", 0, 1, "true"])
def test_strict_must_be_bool_or_none(strict):
    with pytest.raises(ConfigValueError) as info:
        Config(strict=strict)
    assert info.value.key_path == "strict"


def test_source_must_be_path_or_none():
    with pytest.raises(ConfigValueError) as info:
        Config(source="x")  # ty: ignore[invalid-argument-type]  # deliberately wrong type
    assert info.value.key_path == "source"
    assert Config(source=Path("/x")).source == Path("/x")


# Immutability ---------------------------------------------------------------------------------------------------------


def test_config_is_frozen():
    config = Config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.strict = True  # ty: ignore[invalid-assignment]  # frozen dataclass; proving it rejects assignment


def test_mappings_reject_item_assignment():
    config = Config(trusted_endpoint_overrides={JB: [PATRONUS]})
    assert isinstance(config.trusted_endpoint_overrides, MappingProxyType)
    with pytest.raises(TypeError):
        config.trusted_endpoint_overrides[JB] = ()  # ty: ignore[invalid-assignment]  # read-only mapping
    with pytest.raises(TypeError):
        DEFAULT_TRUSTED_ENDPOINTS[JB] = ()  # ty: ignore[invalid-assignment]  # read-only mapping


def test_stored_values_are_tuples():
    config = Config(trusted_endpoint_overrides={JB: [PATRONUS], "https://a.com": PATRONUS})
    assert all(type(v) is tuple for v in config.trusted_endpoint_overrides.values())


def test_config_is_not_hashable():
    with pytest.raises(TypeError, match="unhashable type: 'Config'"):
        hash(Config())


def test_source_mapping_not_aliased_to_input():
    raw = {JB: [PATRONUS]}
    config = Config(trusted_endpoint_overrides=raw)
    raw[JB].append("https://evil.example")
    raw["https://b.com"] = []
    assert dict(config.trusted_endpoint_overrides) == {JB: (PATRONUS, )}


# trusted_patronus_origins ---------------------------------------------------------------------------------------------


def test_default_trust_applies():
    assert Config().trusted_patronus_origins(JB) == (PATRONUS, )


def test_override_replaces_default():
    config = Config(trusted_endpoint_overrides={JB: "https://other.example"})
    assert config.trusted_patronus_origins(JB) == ("https://other.example", )


def test_unknown_issuer_gets_nothing():
    assert Config().trusted_patronus_origins("https://example.com") == ()


def test_issuer_is_normalised():
    assert Config().trusted_patronus_origins("https://JetBrains.team:443/") == (PATRONUS, )


def test_invalid_issuer_raises_value_error():
    with pytest.raises(ValueError):
        Config().trusted_patronus_origins("http://jetbrains.team")


# trust_suggestion -----------------------------------------------------------------------------------------------------


def _parse(snippet: str) -> dict:
    return YAML(typ="safe", pure=True).load(snippet)


def test_suggestion_keeps_effective_list_and_adds_origin():
    parsed = _parse(Config().trust_suggestion(JB, "https://New.example/"))
    assert parsed == {"patronus-trusted-endpoints": {JB: [PATRONUS, "https://new.example"]}}


def test_suggestion_does_not_duplicate_existing_origin():
    parsed = _parse(Config().trust_suggestion(JB, "https://PATRONUS.labs.jb.gg/"))
    assert parsed == {"patronus-trusted-endpoints": {JB: [PATRONUS]}}


def test_suggestion_keeps_other_overrides_and_order():
    config = Config(trusted_endpoint_overrides={"https://a.com": "https://p1.com", JB: "https://p2.com"})
    parsed = _parse(config.trust_suggestion("https://A.com", "https://p3.com"))
    block = parsed["patronus-trusted-endpoints"]
    assert list(block) == ["https://a.com", JB]
    assert block == {"https://a.com": ["https://p1.com", "https://p3.com"], JB: ["https://p2.com"]}


def test_suggestion_for_new_issuer_is_appended():
    config = Config(trusted_endpoint_overrides={"https://a.com": "https://p1.com"})
    block = _parse(config.trust_suggestion("https://b.com", "https://p3.com"))["patronus-trusted-endpoints"]
    assert list(block) == ["https://a.com", "https://b.com"]
    assert block["https://b.com"] == ["https://p3.com"]


def test_suggestion_port_origin_round_trips():
    parsed = _parse(Config().trust_suggestion("https://space.example:8443", "https://patronus.example:9443"))
    assert parsed == {"patronus-trusted-endpoints": {"https://space.example:8443": ["https://patronus.example:9443"]}}


def test_suggestion_is_block_style():
    snippet = Config().trust_suggestion(JB, "https://new.example")
    assert snippet.startswith("patronus-trusted-endpoints:\n")
    assert "{" not in snippet and "[" not in snippet


def test_suggestion_invalid_arguments_raise_value_error():
    with pytest.raises(ValueError):
        Config().trust_suggestion("http://x.com", "https://y.com")
    with pytest.raises(ValueError):
        Config().trust_suggestion(JB, "ftp://y.com")


def test_suggestion_substituted_into_file_loads_to_expected_config(tmp_path):
    file_text = (
        "strict: true\n"
        "patronus-trusted-endpoints:\n"
        '  "https://other.example": "https://p.example"\n'
        '  "https://JetBrains.team/": []\n'
    )
    path = tmp_path / "config.yaml"
    path.write_text(file_text, encoding="utf-8")
    suggestion = load_config(path).trust_suggestion(JB, "https://new.example")

    path.write_text("strict: true\n" + suggestion, encoding="utf-8")
    reloaded = load_config(path)

    assert reloaded.strict is True
    assert dict(reloaded.trusted_endpoint_overrides) == {
        "https://other.example": ("https://p.example", ),
        JB: ("https://new.example", ),
    }
    assert reloaded.trusted_patronus_origins(JB) == ("https://new.example", )


# Imports --------------------------------------------------------------------------------------------------------------


def test_config_module_imports_no_click():
    code = (
        "import sys\n"
        "before = set(sys.modules)\n"
        "assert 'click' not in before, 'click preloaded; the check below would be vacuous'\n"
        "import space.config\n"
        "added = sorted(m for m in set(sys.modules) - before if m == 'click' or m.startswith('click.'))\n"
        "assert not added, added\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
