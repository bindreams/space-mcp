"""A mutation Space confirmed, and a failure that came after it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from types import MappingProxyType

from .formatting import describe_error
from .models.review_ref import ReviewRef


class Mutation(Enum):
    """What took effect."""

    MR_CREATED = auto()
    MR_EDITED = auto()
    COMMENT_POSTED = auto()
    DISCUSSION_CREATED = auto()
    SAFE_MERGE_ACCEPTED = auto()
    RUN_STARTED = auto()


class Inspect(Enum):
    """Where to look at a mutation's result instead of re-running it."""

    VIEW = auto()  # the merge request; a create with no ref falls back to listing by source branch
    TIMELINE = auto()  # the merge request's timeline
    CHECKS = auto()  # the merge request's Patronus runs
    WATCH = auto()  # the run


@dataclass(frozen=True)
class MutationFacts:
    done: str  # what took effect, as a sentence start
    rerun: str  # what not to do, after "do not"
    inspect: Inspect
    needs_review: bool
    mcp_tool: str | None  # the MCP tool not to call again; None when MCP adds no hint


MUTATION_FACTS: Mapping[Mutation, MutationFacts] = MappingProxyType({
    Mutation.MR_CREATED: MutationFacts(
        "The merge request was created", "re-run the create", Inspect.VIEW, False, "put_merge_request"
    ),
    Mutation.MR_EDITED: MutationFacts("The edit was applied", "re-run it", Inspect.VIEW, True, "patch_merge_request"),
    Mutation.COMMENT_POSTED: MutationFacts(
        "The comment was posted", "re-run it", Inspect.TIMELINE, True, "post_merge_request_comment"
    ),
    Mutation.DISCUSSION_CREATED: MutationFacts(
        "The code discussion was created", "re-run it", Inspect.TIMELINE, True, "post_code_discussion"
    ),
    # MCP: put_patronus_dry_run always appends its own follow-up note
    Mutation.SAFE_MERGE_ACCEPTED: MutationFacts(
        "A run may have started", "re-run it before checking", Inspect.CHECKS, True, None
    ),
    # MCP has no watch
    Mutation.RUN_STARTED: MutationFacts("The run was started", "re-run it", Inspect.WATCH, False, None),
})


@dataclass(frozen=True)
class MutationTarget:
    """What to inspect instead of re-running the mutation; fields the caller couldn't know are None."""

    project: str
    review: ReviewRef | None = None
    repo: str | None = None
    source_branch: str | None = None
    run_id: str | None = None


def created_review_ref(data: object) -> ReviewRef | None:
    """The ref of a just-created MR from its raw response: the number when usable, else the id, else None."""
    if not isinstance(data, dict):
        return None
    number = data.get("number")
    if isinstance(number, int) and not isinstance(number, bool) and number > 0:
        return ReviewRef(number=number)
    mr_id = data.get("id")
    if isinstance(mr_id, str) and mr_id:
        return ReviewRef(id=mr_id)
    return None


def _message(mutation: Mutation, target: MutationTarget, cause: BaseException, applied: tuple[str, ...]) -> str:
    c = describe_error(cause)
    if mutation is Mutation.MR_CREATED:
        subject = "a merge request" if target.review is None else f"merge request {target.review}"
        return f"{subject} was created, but reading it failed: {c}"
    if mutation is Mutation.MR_EDITED:
        return f"edit applied ({', '.join(applied)}) but re-fetching the updated MR failed: {c}"
    if mutation is Mutation.RUN_STARTED:
        return f"run {target.run_id} was started, but watching it failed: {c}"
    assert target.review is not None or not MUTATION_FACTS[mutation].needs_review, f"{mutation} needs its review"
    if mutation is Mutation.COMMENT_POSTED:
        return f"comment posted on merge request {target.review}, but reading the response failed: {c}"
    if mutation is Mutation.DISCUSSION_CREATED:
        return f"code discussion created on merge request {target.review}, but reading the response failed: {c}"
    assert mutation is Mutation.SAFE_MERGE_ACCEPTED, mutation
    return (
        f"Space accepted the safe-merge request for merge request {target.review}, "
        f"but reading the response failed: {c}"
    )


class MutationCompletedError(Exception):
    """Space confirmed a mutation, then reading its result failed. Never re-run the mutation; inspect the target.

    Client methods raise it for every Exception after the 2xx, AssertionError included: re-raised bare, a contract
    violation would hide the confirmed mutation wherever only the message is shown.
    """

    def __init__(
        self, mutation: Mutation, target: MutationTarget, cause: BaseException, *, applied: Sequence[str] = ()
    ):
        self.mutation = mutation
        self.target = target
        self.cause = cause
        self.applied = tuple(applied)
        super().__init__(_message(mutation, target, cause, self.applied))
