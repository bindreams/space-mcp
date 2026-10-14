"""The MCP merge-request state filter accepts only real states, in both modes."""

import logging
from unittest.mock import MagicMock

import pytest

from space.mcp.server import SpaceMCP
from space.models import MRStateFilter

_BOTH_MODES = pytest.mark.parametrize(
    "mode", ["strict", pytest.param("permissive", marks=pytest.mark.unrecognised_api_value)]
)
_MESSAGE = "expected one of Opened, Closed, Merged, RequiresAuthorAttention, NeedsReview"


@pytest.fixture()
def mcp():
    server = SpaceMCP(token="test-token")
    server.space_client = MagicMock()
    server.patronus_client = MagicMock()
    calls: list[dict] = []

    async def list_merge_requests(**kwargs):
        calls.append(kwargs)
        return
        yield

    server.space_client.list_merge_requests = list_merge_requests
    server.calls = calls  # ty: ignore[unresolved-attribute]  # test-only bookkeeping on the server
    return server


@_BOTH_MODES
@pytest.mark.parametrize("member", [m for m in MRStateFilter if m is not MRStateFilter.UNKNOWN], ids=str)
async def test_each_real_state_is_sent(mcp, mode, member):
    await mcp.get_merge_requests("ij", "ultimate", state=member.value)
    assert [call["state"] for call in mcp.calls] == [member]


@_BOTH_MODES
@pytest.mark.parametrize("value", ["Unknown", "opened", " Opened", "Opened ", "bogus"])
async def test_invalid_state_is_rejected(mcp, caplog, mode, value):
    caplog.set_level(logging.DEBUG, logger="space.models")
    result = await mcp.get_merge_requests("ij", "ultimate", state=value)
    assert result == f"**Error:** invalid state {value!r}: {_MESSAGE}"
    assert mcp.calls == []
    assert [r for r in caplog.records if r.name == "space.models"] == []


@_BOTH_MODES
@pytest.mark.parametrize("value", ["", None])
async def test_empty_or_omitted_state_means_no_filter(mcp, mode, value):
    await mcp.get_merge_requests("ij", "ultimate", state=value)
    assert [call["state"] for call in mcp.calls] == [None]
