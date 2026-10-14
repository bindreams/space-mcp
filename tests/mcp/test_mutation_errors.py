"""MCP errors for a mutation Space confirmed: say it took effect, and how to inspect it."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from space.client import MergeRequestEditError
from space.mcp.server import SpaceMCP
from space.models import ReviewRef
from space.mutation import Mutation, MutationCompletedError, MutationTarget


@pytest.fixture()
def mcp():
    server = SpaceMCP(token="test-token")
    server.space_client = MagicMock()
    server.patronus_client = MagicMock()
    return server


def _created(review):
    target = MutationTarget("ij", review, repo="ultimate", source_branch="feat")
    return MutationCompletedError(Mutation.MR_CREATED, target, KeyError("id"))


def _edited(review):
    return MutationCompletedError(Mutation.MR_EDITED, MutationTarget("ij", review), KeyError("id"), applied=["title"])


class TestCreate:

    @pytest.mark.parametrize(
        ("review", "inspect"),
        [
            (ReviewRef(number=194200), "Inspect MR #194200 with `get_merge_request`."),
            (ReviewRef(id="abc"), "Call `get_merge_request` with review_id `id:abc`."),
            (None, "Find it with `get_merge_requests` and branch `feat`."),
        ],
        ids=["number", "id", "no-ref"],
    )
    async def test_unreadable_create(self, mcp, review, inspect):
        err = _created(review)
        mcp.space_client.create_merge_request = AsyncMock(side_effect=err)
        result = await mcp.put_merge_request("ij", "ultimate", "feat", "master", "T")
        assert result == (
            f"**Error:** {err}\n\n"
            f"The merge request was created; do not call `put_merge_request` again. {inspect}"
        )


class TestEdit:

    @pytest.mark.parametrize(
        ("review", "inspect"),
        [
            (ReviewRef(number=42), "Inspect MR #42 with `get_merge_request`."),
            (ReviewRef(id="abc"), "Call `get_merge_request` with review_id `id:abc`."),
        ],
        ids=["number", "id"],
    )
    async def test_refetch_failure(self, mcp, review, inspect):
        err = _edited(review)
        mcp.space_client.edit_merge_request = AsyncMock(side_effect=err)
        result = await mcp.patch_merge_request("ij", review.label, title="T")
        assert result == (
            f"**Error:** {err}\n\nThe edit was applied; do not call `patch_merge_request` again. {inspect}"
        )

    async def test_partial_edit_keeps_its_prefix(self, mcp):
        mcp.space_client.edit_merge_request = AsyncMock(side_effect=MergeRequestEditError(["title"], RuntimeError("x")))
        result = await mcp.patch_merge_request("ij", "42", title="T", description="D")
        assert result.startswith("**Partial edit:** edit partially applied (title updated) before failing: x")
