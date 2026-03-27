"""Tests for git context inference."""

from unittest.mock import patch

from space.context import (
    GitContext,
    _parse_remote_url,
    detect_git_context,
    resolve_context,
)


class TestParseRemoteUrl:

    def test_https_url(self):
        result = _parse_remote_url("https://git.jetbrains.team/ij/ultimate.git")
        assert result == ("ij", "ultimate")

    def test_https_url_no_git_suffix(self):
        result = _parse_remote_url("https://git.jetbrains.team/ij/ultimate")
        assert result == ("ij", "ultimate")

    def test_ssh_url(self):
        result = _parse_remote_url("ssh://git@git.jetbrains.team/ij/ultimate")
        assert result == ("ij", "ultimate")

    def test_ssh_url_with_git_suffix(self):
        result = _parse_remote_url("ssh://git@git.jetbrains.team/ij/ultimate.git")
        assert result == ("ij", "ultimate")

    def test_scp_style_url(self):
        result = _parse_remote_url("git@git.jetbrains.team:ij/ultimate.git")
        assert result == ("ij", "ultimate")

    def test_non_space_url_returns_none(self):
        result = _parse_remote_url("https://github.com/user/repo.git")
        assert result is None

    def test_empty_string_returns_none(self):
        result = _parse_remote_url("")
        assert result is None


class TestDetectGitContext:

    @patch("space.context._run_git")
    def test_full_context(self, mock_git):

        def side_effect(*args):
            if args == ("symbolic-ref", "--short", "HEAD"):
                return "azhukova/fix-auth"
            if args == ("remote", "get-url", "origin"):
                return "https://git.jetbrains.team/ij/ultimate.git"
            return None

        mock_git.side_effect = side_effect
        ctx = detect_git_context()
        assert ctx.project == "ij"
        assert ctx.repo == "ultimate"
        assert ctx.branch == "azhukova/fix-auth"

    @patch("space.context._run_git")
    def test_no_git_repo(self, mock_git):
        mock_git.return_value = None
        ctx = detect_git_context()
        assert ctx.project is None
        assert ctx.repo is None
        assert ctx.branch is None

    @patch("space.context._run_git")
    def test_non_space_remote(self, mock_git):

        def side_effect(*args):
            if args == ("symbolic-ref", "--short", "HEAD"):
                return "main"
            if args == ("remote", "get-url", "origin"):
                return "https://github.com/user/repo.git"
            return None

        mock_git.side_effect = side_effect
        ctx = detect_git_context()
        assert ctx.project is None
        assert ctx.repo is None
        assert ctx.branch == "main"


class TestResolveContext:

    @patch("space.context.detect_git_context")
    def test_explicit_args_override_git(self, mock_detect):
        mock_detect.return_value = GitContext(project="git-proj", repo="git-repo", branch="git-branch")
        ctx = resolve_context(project="explicit-proj", repo="explicit-repo")
        assert ctx.project == "explicit-proj"
        assert ctx.repo == "explicit-repo"
        assert ctx.branch == "git-branch"  # branch from git since not overridden

    @patch("space.context.detect_git_context")
    def test_env_vars_override_git(self, mock_detect, monkeypatch):
        mock_detect.return_value = GitContext(project="git-proj", repo="git-repo", branch="git-branch")
        monkeypatch.setenv("SPACE_PROJECT", "env-proj")
        monkeypatch.setenv("SPACE_REPO", "env-repo")
        ctx = resolve_context()
        assert ctx.project == "env-proj"
        assert ctx.repo == "env-repo"

    @patch("space.context.detect_git_context")
    def test_explicit_args_override_env(self, mock_detect, monkeypatch):
        mock_detect.return_value = GitContext()
        monkeypatch.setenv("SPACE_PROJECT", "env-proj")
        ctx = resolve_context(project="explicit-proj")
        assert ctx.project == "explicit-proj"

    @patch("space.context.detect_git_context")
    def test_falls_through_to_none(self, mock_detect):
        mock_detect.return_value = GitContext()
        ctx = resolve_context()
        assert ctx.project is None
        assert ctx.repo is None
        assert ctx.branch is None
