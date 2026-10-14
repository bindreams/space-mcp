"""CLI rendering of errors that need a hint: what happened, and what to run next."""

from __future__ import annotations

import os
import shlex
import subprocess
from typing import TYPE_CHECKING

import click

from ..models.enums import UnrecognisedApiValue
from ..mutation import MUTATION_FACTS, Inspect, MutationCompletedError

if TYPE_CHECKING:
    from .app import CliState

RERUN_HINT = "Run as `space --no-strict <command>` to treat unrecognised values as UNKNOWN."


def _command_line(args: list[str], *, windows: bool) -> str:
    return subprocess.list2cmdline(args) if windows else shlex.join(args)


def _cite(verb: str, command: str) -> str:
    """`<verb> `command`.`, or the command alone on the next line when a backtick would break the inline form."""
    if "`" in command:
        return f"{verb}:\n  {command}"
    return f"{verb} `{command}`."


def _mutation_hint(err: MutationCompletedError, repo: str, *, windows: bool) -> str:
    facts = MUTATION_FACTS[err.mutation]
    target = err.target
    ref = target.review
    assert ref is not None or not facts.needs_review, err.mutation
    space = ["space", "--no-strict"] if isinstance(err.cause, UnrecognisedApiValue) else ["space"]
    scoped = [*space, "-P", target.project, "-R", repo]

    def cite(verb: str, *args: str, base: list[str] = scoped) -> str:
        return _cite(verb, _command_line([*base, *args], windows=windows))

    match facts.inspect:
        case Inspect.VIEW if ref is not None:
            inspect = cite("Inspect it with", "mr", "view", ref.label)
        case Inspect.VIEW:
            inspect = cite("Find it with", "mr", "list", "-H", target.source_branch or "<branch>")
        case Inspect.TIMELINE:
            assert ref is not None
            inspect = cite("See it with", "mr", "timeline", ref.label)
        case Inspect.CHECKS:
            assert ref is not None
            if ref.number is not None:
                inspect = cite("Check with", "mr", "checks", str(ref.number))
            else:
                inspect = "Check the merge request's Patronus runs before re-running."
        case Inspect.WATCH:
            inspect = cite("Watch it with", "run", "watch", target.run_id or "<run-id>", base=space)
    return f"{facts.done}; do not {facts.rerun}. {inspect}"


def mutation_click_error(
    err: MutationCompletedError, state: CliState | None, *, windows: bool = os.name == "nt"
) -> click.ClickException:
    """The CLI error for a confirmed mutation: the message, then how to inspect the result instead of re-running.

    `windows` picks the quoting the hint's command uses.
    """
    repo = err.target.repo or (state.context.repo if state is not None else None) or "<repo>"
    return click.ClickException(f"{err}\n{_mutation_hint(err, repo, windows=windows)}")
