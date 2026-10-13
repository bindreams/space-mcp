"""Files the loader itself rejects."""

import subprocess
import sys

import pytest
from ruamel.yaml.reader import ReaderError

from space.config import ConfigValueError, load_config

from .helpers import ALIAS_KEY, MERGE, NON_SCALAR_KEY, NULL, ORDERED, UNKNOWN, VALUE_KEY, assert_error, message, rejected, write


def test_unknown_top_level_key(tmp_path):
    assert_error(write(tmp_path, "colour: red\n"), '"colour"', UNKNOWN)


def test_non_str_top_level_key(tmp_path):
    assert_error(write(tmp_path, "1: x\n"), "<int key>", UNKNOWN)


@pytest.mark.parametrize(
    ("content", "type_name"),
    [("- a\n", "list"), ("5\n", "int"), ("hello\n", "str"), ("true\n", "bool")],
)
def test_top_level_must_be_a_mapping(tmp_path, content, type_name):
    path = write(tmp_path, content)
    assert_error(path, None, f"expected a mapping at the top level, got {type_name}")


def test_strict_null(tmp_path):
    assert_error(write(tmp_path, "strict: null\n"), "strict", NULL)
    assert_error(write(tmp_path, "strict:\n"), "strict", NULL)


def test_endpoints_null(tmp_path):
    assert_error(write(tmp_path, "patronus-trusted-endpoints: null\n"), "patronus-trusted-endpoints", NULL)


def test_endpoints_list(tmp_path):
    error = assert_error(
        write(tmp_path, "patronus-trusted-endpoints: [a]\n"), "patronus-trusted-endpoints",
        "expected a mapping, got list"
    )
    assert isinstance(error.__cause__, ConfigValueError)


def test_merge_at_top_level(tmp_path):
    assert_error(write(tmp_path, "base: &b {strict: true}\n<<: *b\n"), None, MERGE)


def test_merge_under_endpoints(tmp_path):
    content = 'patronus-trusted-endpoints:\n  <<: {"https://a.example": []}\n'
    assert_error(write(tmp_path, content), "patronus-trusted-endpoints", MERGE)


def test_merge_in_sequence_item(tmp_path):
    assert_error(write(tmp_path, "items:\n  - a: 1\n  - <<: {}\n"), '"items".[1]', MERGE)


@pytest.mark.parametrize("content", ["1: {<<: {}}\n", "true: {<<: {}}\n"])
def test_merge_under_non_str_key(tmp_path, content):
    assert_error(write(tmp_path, content), "<non-str key>", MERGE)


def test_merge_in_nested_mapping(tmp_path):
    assert_error(write(tmp_path, "a:\n  b:\n    <<: {}\n"), '"a"."b"', MERGE)


def test_merge_inside_a_key_is_a_non_scalar_key(tmp_path):
    assert_error(write(tmp_path, "a:\n  ? {<<: {}}\n  : 1\n"), '"a"', NON_SCALAR_KEY)


def test_merge_in_anchored_mapping_reported_at_first_occurrence(tmp_path):
    content = "b:\n  c: &x\n    <<: {}\nd: *x\n"
    assert_error(write(tmp_path, content), '"b"."c"', MERGE)


def test_first_merge_in_document_order_wins(tmp_path):
    assert_error(write(tmp_path, "a:\n  <<: {}\n<<: {}\n"), '"a"', MERGE)
    assert_error(write(tmp_path, "<<: {}\na:\n  <<: {}\n"), None, MERGE)


def test_recursive_alias_terminates(tmp_path):
    assert_error(write(tmp_path, "a: &x\n  self: *x\n"), '"a"', UNKNOWN)


def test_top_level_sequence_holding_a_merge_gets_the_shape_error(tmp_path):
    assert_error(write(tmp_path, "- <<: {}\n"), None, "expected a mapping at the top level, got list")


@pytest.mark.parametrize("tag", ["omap", "pairs"])
@pytest.mark.parametrize(
    ("template", "key_path"),
    [
        ("strict: !!{tag} [a: 1]\n", "strict"),
        ("strict: !!{tag} [a: 1, a: 2]\n", "strict"),
        ("patronus-trusted-endpoints: !!{tag} []\n", "patronus-trusted-endpoints"),
        (
            'patronus-trusted-endpoints: !!{tag} [{{"https://jetbrains.team": []}}, '
            '{{"https://jetbrains.team": ["https://x.example"]}}]\n',
            "patronus-trusted-endpoints",
        ),
        ("a:\n  b: !!{tag} [c: 1]\n", '"a"."b"'),
    ],
)
def test_ordered_map_tags_rejected(tmp_path, tag, template, key_path):
    assert_error(write(tmp_path, template.format(tag=tag)), key_path, ORDERED)


@pytest.mark.parametrize(
    "content",
    [
        "!!omap [strict: true]\n",
        "!!omap {strict: true}\n",
        "!!omap [strict: true, strict: false]\n",
        "!!pairs [strict: true]\n",
    ],
)
def test_top_level_ordered_map_is_rejected(tmp_path, content):
    path = write(tmp_path, content)
    error = assert_error(path, None, ORDERED)
    assert str(error) == message(path, None, ORDERED)


@pytest.mark.parametrize("content", ["!!set {}\n", "!!set {strict: null}\n", "!!set\n? strict\n"])
def test_top_level_set_gets_the_shape_error(tmp_path, content):
    assert_error(write(tmp_path, content), None, "expected a mapping at the top level, got set")


@pytest.mark.parametrize(
    ("content", "type_name"),
    [
        ("- !!int abc\n", "list"),
        ("- {a: 1, a: 2}\n", "list"),
        ("- !foo x\n", "list"),
        ("!!set {<<: {}}\n", "set"),
        ("!!set {a, a}\n", "set"),
    ],
)
def test_top_level_shape_is_checked_before_constructing(tmp_path, content, type_name):
    assert_error(write(tmp_path, content), None, f"expected a mapping at the top level, got {type_name}")


def test_assert_guarded_ruamel_checks_are_not_relied_on_under_python_dash_o(tmp_path):
    # pytest strips asserts under -O, so only a subprocess proves ruamel's assert-based checks are not relied on.
    contents = [
        "strict: !!omap [a: 1, a: 2]\n",
        "strict: !!pairs [a: 1, a: 2]\n",
        'patronus-trusted-endpoints: !!omap [{"https://x.com": []}, {"https://x.com": ["https://p.com"]}]\n',
        'patronus-trusted-endpoints: !!pairs [{"https://x.com": []}, {"https://x.com": ["https://p.com"]}]\n',
        "%YAML 1.3\n---\nstrict: true\n",
        "%YAML 1.0\n---\nstrict: true\n",
    ]
    paths = []
    for i, content in enumerate(contents):
        (tmp_path / str(i)).mkdir()
        paths.append(str(write(tmp_path / str(i), content)))
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from space.config import ConfigError, load_config\n"
        "assert not __debug__\n"
        "for p in sys.argv[1:]:\n"
        "    try:\n"
        "        load_config(Path(p))\n"
        "    except ConfigError as e:\n"
        "        print(e.key_path, e.reason, sep='|')\n"
        "    else:\n"
        "        print('LOADED')\n"
    )
    result = subprocess.run([sys.executable, "-O", "-c", code, *paths], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f"strict|{ORDERED}"] * 2 + [f"patronus-trusted-endpoints|{ORDERED}"] * 2 + [
        "None|unsupported YAML version 1.3; use 1.2",
        "None|unsupported YAML version 1.0; use 1.2",
    ]


def _alias_chain() -> str:
    # `l7` expands to 10**8 leaves as a tree; constructing it as a key must not walk it.
    lines = ["l0: &l0 [" + ", ".join(["x"] * 10) + "]"]
    lines += [f"l{i}: &l{i} [" + ", ".join([f"*l{i - 1}"] * 10) + "]" for i in range(1, 8)]
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    ("tail", "key_path"),
    [
        ("? [*l7]\n: x\n", None),
        ("strict:\n  ? [*l7]\n  : x\n", "strict"),
        ("patronus-trusted-endpoints:\n  ? [*l7]\n  : []\n", "patronus-trusted-endpoints"),
        ("a:\n  b:\n    ? [x]\n    : 1\n", '"a"."b"'),
        ("? {a: 1}\n: x\n", None),
    ],
)
def test_non_scalar_keys_are_rejected_before_constructing(tmp_path, tail, key_path):
    assert_error(write(tmp_path, _alias_chain() + tail), key_path, NON_SCALAR_KEY)


@pytest.mark.parametrize(
    ("content", "key_path"),
    [
        ("&k a: 1\n*k : 2\n", None),
        ("strict: true\nl: &l [x]\n*l : 2\n", None),
        ("patronus-trusted-endpoints:\n  &k https://a.example: []\n  *k : []\n", "patronus-trusted-endpoints"),
        ("a:\n  &k b: 1\nc:\n  *k : 2\n", '"c"'),
    ],
)
def test_alias_keys_are_rejected(tmp_path, content, key_path):
    assert_error(write(tmp_path, content), key_path, ALIAS_KEY)


@pytest.mark.parametrize(
    ("content", "key_path", "reason"),
    [
        ("strict: !!bool {=: true, junk: 1}\n", "strict", 'tag "tag:yaml.org,2002:bool" is not supported on a mapping'),
        (
            "strict: !!bool {=: true, =: false}\n", "strict",
            'tag "tag:yaml.org,2002:bool" is not supported on a mapping'
        ),
        (
            'patronus-trusted-endpoints:\n  "https://a.example": !!str {=: "https://b.example", ignored: 1}\n',
            'patronus-trusted-endpoints."https://a.example"',
            'tag "tag:yaml.org,2002:str" is not supported on a mapping',
        ),
        ("strict: !foo {a: 1}\n", "strict", 'tag "!foo" is not supported on a mapping'),
        ("strict: {=: true}\n", "strict", VALUE_KEY),
        ("{=: true}\n", None, VALUE_KEY),
    ],
)
def test_value_keys_and_odd_mapping_tags_are_rejected(tmp_path, content, key_path, reason):
    assert_error(write(tmp_path, content), key_path, reason)


@pytest.mark.parametrize(
    ("content", "key_path", "reason"),
    [
        ("1: a\n1.0: b\n", "<int key>", UNKNOWN),
        ("true: a\n1: b\n", "<bool key>", UNKNOWN),
        ("true: a\nTrue: b\n", "<bool key>", UNKNOWN),
        (
            "patronus-trusted-endpoints: {1: x, true: y}\n", "patronus-trusted-endpoints.<int key>",
            "key must be a string"
        ),
    ],
)
def test_keys_distinct_as_yaml_nodes_are_not_duplicates(tmp_path, content, key_path, reason):
    assert_error(write(tmp_path, content), key_path, reason)


def test_yaml_11_rejected(tmp_path):
    assert_error(write(tmp_path, "%YAML 1.1\n---\nstrict: true\n"), None, "unsupported YAML version 1.1; use 1.2")


@pytest.mark.parametrize("version", ["1.0", "1.3", "1.10", "2.0", "0.9"])
def test_other_yaml_versions_rejected(tmp_path, version):
    content = f"%YAML {version}\n---\nstrict: true\n"
    assert_error(write(tmp_path, content), None, f"unsupported YAML version {version}; use 1.2")


def test_invalid_utf8_reports_reason_and_byte_position(tmp_path):
    error = assert_error(
        write(tmp_path, b"strict: \xc3\x28\n"), None,
        'invalid YAML (ReaderError): "invalid continuation byte" at byte 8'
    )
    assert type(error.__cause__) is ReaderError


def test_parser_not_reused_after_yaml_11(tmp_path):
    rejected(write(tmp_path, "%YAML 1.1\n---\nstrict: true\n"))
    assert load_config(write(tmp_path, "strict: true\n")).strict is True
