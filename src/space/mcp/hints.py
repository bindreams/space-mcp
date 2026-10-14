"""MCP hints: how an agent recovers from an error without repeating a mutation."""

from __future__ import annotations

import json

from ..models.enums import UnrecognisedApiValue
from ..mutation import Mutation, MutationCompletedError
from ..strict import StrictSetting, StrictSource

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
    return f"inspect it with `get_merge_request` and review_id `{ref.label}`"


def restart_hint(setting: StrictSetting | None) -> str:
    """How to restart the server with strict mode off, naming the setting that turned it on."""
    if setting is not None and setting.source is StrictSource.ENV:
        return "Set SPACE_STRICT=0 and restart the MCP server"
    if setting is not None and setting.source is StrictSource.CONFIG:
        return f"Set strict: false in {json.dumps(str(setting.config_file))} and restart the MCP server"
    return "Restart the MCP server with SPACE_STRICT=0"


def strict_sentence(setting: StrictSetting | None) -> str:
    return f"{restart_hint(setting)} to treat unrecognised values as UNKNOWN."


def mutation_hint(err: MutationCompletedError, setting: StrictSetting | None) -> str:
    """The paragraph after a confirmed mutation's error, or "" for kinds whose tool supplies its own guidance."""
    if err.mutation not in _TOOLS:
        return ""
    lead = f"{_LEADS[err.mutation]}; do not call `{_TOOLS[err.mutation]}` again."
    inspect = _inspect(err)
    if isinstance(err.cause, UnrecognisedApiValue):
        return f"{lead} {restart_hint(setting)}, then {inspect}."
    return f"{lead} {inspect[0].upper()}{inspect[1:]}."
