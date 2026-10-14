"""MCP hints: how an agent recovers from an error without repeating a mutation."""

from __future__ import annotations

import json

from ..models.enums import UnrecognisedApiValue
from ..mutation import MUTATION_FACTS, Inspect, MutationCompletedError
from ..strict import StrictSetting, StrictSource


def _inspect(err: MutationCompletedError) -> str:
    facts = MUTATION_FACTS[err.mutation]
    ref = err.target.review
    if facts.inspect is Inspect.TIMELINE:
        assert ref is not None
        return f"check it with `get_merge_request_timeline` for review_id `{ref.label}`"
    assert facts.inspect is Inspect.VIEW, facts.inspect
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
    facts = MUTATION_FACTS[err.mutation]
    if facts.mcp_tool is None:
        return ""
    lead = f"{facts.done}; do not call `{facts.mcp_tool}` again."
    inspect = _inspect(err)
    if isinstance(err.cause, UnrecognisedApiValue):
        return f"{lead} {restart_hint(setting)}, then {inspect}."
    return f"{lead} {inspect[0].upper()}{inspect[1:]}."
