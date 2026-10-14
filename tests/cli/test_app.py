"""Tests for CLI app-level functionality (parse_mr_ref, top-level commands)."""

import click
import pytest

from space.cli.app import ParsedMrRef, parse_mr_ref
from space.models import ReviewRef

from .conftest import run_cli

_URL = "https://jetbrains.team/p/ij/reviews"


class TestParseMrRef:

    @pytest.mark.parametrize("ref", [None, ""])
    def test_no_ref_means_current_branch(self, ref):
        assert parse_mr_ref(ref) == ParsedMrRef()

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("188120", ReviewRef(number=188120)),
            ("id:123456", ReviewRef(id="123456")),
            ("number:42", ReviewRef(number=42)),
        ],
    )
    def test_review_ref(self, text, expected):
        assert parse_mr_ref(text) == ParsedMrRef(ref=expected)

    @pytest.mark.parametrize(
        "url",
        [f"{_URL}/188120/timeline", f"{_URL}/188120", f"{_URL}/188120?x=1", f"{_URL}/188120#c"],
    )
    def test_url(self, url):
        assert parse_mr_ref(url) == ParsedMrRef(ref=ReviewRef(number=188120), project="ij")

    @pytest.mark.parametrize(
        "text",
        [
            "azhukova/fix-auth",
            "²",
            "١٢",
            f"{_URL}/١٢/timeline",
            f"{_URL}/12١٢/timeline",
            f"{_URL}/12²",
            f"{_URL}/12abc/timeline",
            f"{_URL}/12\n",
            f"{_URL}/12١٢#/p/ij/reviews/7",
            f"{_URL}/12abc/files?from=/p/other/reviews/5",
            "http://[jetbrains.team/p/ij/reviews/5",
        ],
    )
    def test_branch_name(self, text):
        assert parse_mr_ref(text) == ParsedMrRef(branch=text)

    @pytest.mark.parametrize("text", ["0", "id:", f"{_URL}/0/timeline"])
    def test_invalid_review_ref(self, text):
        with pytest.raises(click.BadParameter):
            parse_mr_ref(text)


class TestTopLevel:

    def test_help(self):
        result = run_cli("--help")
        assert result.exit_code == 0
        assert "space" in result.output.lower()
        assert "mr" in result.output
        assert "run" in result.output
        assert "auth" in result.output
        assert "api" in result.output
        assert "status" in result.output

    def test_version(self):
        result = run_cli("--version")
        assert result.exit_code == 0
        assert "1.0.0" in result.output

    def test_no_command_shows_help(self):
        result = run_cli()
        assert result.exit_code == 0
        assert "Commands:" in result.output
