"""CLI rendering of errors that need a hint: what happened, and what to run next."""

from __future__ import annotations

import os
import shlex
import subprocess
from typing import TYPE_CHECKING

import click

from ..models.enums import UnrecognisedApiValue
from ..mutation import Mutation, MutationCompletedError

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
    target = err.target
    space = ["space", "--no-strict"] if isinstance(err.cause, UnrecognisedApiValue) else ["space"]
    scoped = [*space, "-P", target.project, "-R", repo]
    ref = target.review

    def cite(verb: str, *args: str) -> str:
        return _cite(verb, _command_line([*scoped, *args], windows=windows))

    match err.mutation:
        case Mutation.MR_CREATED:
            lead = "The merge request was created; do not re-run the create."
            if ref is not None:
                inspect = cite("Inspect it with", "mr", "view", ref.label)
            else:
                inspect = cite("Find it with", "mr", "list", "-H", target.source_branch or "<branch>")
        case Mutation.MR_EDITED:
            assert ref is not None
            lead = "The edit was applied; do not re-run it."
            inspect = cite("Inspect it with", "mr", "view", ref.label)
        case Mutation.COMMENT_POSTED | Mutation.DISCUSSION_CREATED:
            assert ref is not None
            what = "comment was posted" if err.mutation is Mutation.COMMENT_POSTED else "code discussion was created"
            lead = f"The {what}; do not re-run it."
            inspect = cite("See it with", "mr", "timeline", ref.label)
        case Mutation.SAFE_MERGE_ACCEPTED:
            assert ref is not None
            lead = "A run may have started; do not re-run it before checking."
            if ref.number is not None:
                inspect = cite("Check with", "mr", "checks", str(ref.number))
            else:
                inspect = "Check the merge request's Patronus runs before re-running."
        case Mutation.RUN_STARTED:
            lead = "The run was started; do not re-run it."
            command = _command_line([*space, "run", "watch", target.run_id or "<run-id>"], windows=windows)
            inspect = _cite("Watch it with", command)
    return f"{lead} {inspect}"


def mutation_click_error(
    err: MutationCompletedError, state: CliState | None, *, windows: bool = os.name == "nt"
) -> click.ClickException:
    """The CLI error for a confirmed mutation: the message, then how to inspect the result instead of re-running.

    `windows` picks the quoting the hint's command uses.
    """
    repo = err.target.repo or (state.context.repo if state is not None else None) or "<repo>"
    return click.ClickException(f"{err}\n{_mutation_hint(err, repo, windows=windows)}")
