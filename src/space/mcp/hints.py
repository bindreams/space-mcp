"""MCP hints: how an agent recovers from an error without repeating a mutation."""

from __future__ import annotations

from ..mutation import Mutation, MutationCompletedError
from ..strict import StrictSetting

_TOOLS = {
    Mutation.MR_CREATED: "put_merge_request",
    Mutation.MR_EDITED: "patch_merge_request",
    Mutation.COMMENT_POSTED: "post_merge_request_comment",
    Mutation.DISCUSSION_CREATED: "post_code_discussion",
}

_LEADS = {
    Mutation.MR_CREATED: "The merge request was created",
    Mutation.MR_EDITED: "The edit was applied",
    Mutation.COMMENT_POSTED: "The comment was posted",
    Mutation.DISCUSSION_CREATED: "The code discussion was created",
}


def _inspect(err: MutationCompletedError) -> str:
    ref = err.target.review
    if err.mutation in (Mutation.COMMENT_POSTED, Mutation.DISCUSSION_CREATED):
        assert ref is not None
        return f"check it with `get_merge_request_timeline` for review_id `{ref.label}`"
    if ref is None:
        return f"find it with `get_merge_requests` and branch `{err.target.source_branch}`"
    if ref.number is not None:
        return f"inspect MR {ref} with `get_merge_request`"
    return f"call `get_merge_request` with review_id `{ref.label}`"


def mutation_hint(err: MutationCompletedError, setting: StrictSetting | None) -> str:
    """The paragraph after a confirmed mutation's error, or "" for kinds whose tool supplies its own guidance."""
    if err.mutation not in _TOOLS:
        return ""
    inspect = _inspect(err)
    return f"{_LEADS[err.mutation]}; do not call `{_TOOLS[err.mutation]}` again. {inspect[0].upper()}{inspect[1:]}."
