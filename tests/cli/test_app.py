"""Tests for CLI app-level functionality (parse_mr_ref, top-level commands)."""

from space.cli.app import parse_mr_ref

from .conftest import run_cli


class TestParseMrRef:

    def test_none(self):
        result = parse_mr_ref(None)
        assert result["number"] is None
        assert result["branch"] is None

    def test_numeric(self):
        result = parse_mr_ref("188120")
        assert result["number"] == "188120"
        assert result["branch"] is None

    def test_url(self):
        result = parse_mr_ref("https://jetbrains.team/p/ij/reviews/188120/timeline")
        assert result["number"] == "188120"
        assert result["project"] == "ij"

    def test_branch_name(self):
        result = parse_mr_ref("azhukova/fix-auth")
        assert result["branch"] == "azhukova/fix-auth"
        assert result["number"] is None


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
