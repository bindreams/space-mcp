"""Tests for the overlap-based pagination wrapper."""
from __future__ import annotations

import pytest

from space.pagination import paginated_fetch


def _make_items(*ids: str) -> list[dict]:
    """Create a list of dicts with the given ids."""
    return [{"id": id_} for id_ in ids]


class TestSinglePage:

    async def test_single_page(self):
        """All results on one page (< page_size). No second request."""
        calls: list[tuple[int, int]] = []

        async def fetch(skip: int, top: int) -> list[dict]:
            calls.append((skip, top))
            if skip == 0:
                return _make_items("a", "b", "c")
            return []

        result = await paginated_fetch(fetch, page_size=10)
        assert [r["id"] for r in result] == ["a", "b", "c"]
        assert len(calls) == 1  # no second request

    async def test_empty_results(self):
        """API returns empty first page → empty result."""

        async def fetch(skip: int, top: int) -> list[dict]:
            return []

        result = await paginated_fetch(fetch, page_size=10)
        assert result == []


class TestNormalStitching:

    async def test_multi_page_normal_stitching(self):
        """Two pages with correct 1-item overlap. All items collected."""
        page_size = 3

        async def fetch(skip: int, top: int) -> list[dict]:
            if skip == 0:
                return _make_items("a", "b", "c")
            if skip == 2:  # page_size - 1
                return _make_items("c", "d", "e")
            return []

        result = await paginated_fetch(fetch, page_size=page_size)
        assert [r["id"] for r in result] == ["a", "b", "c", "d", "e"]

    async def test_deduplication(self):
        """Same item id on different pages appears only once."""
        page_size = 3

        async def fetch(skip: int, top: int) -> list[dict]:
            if skip == 0:
                return _make_items("a", "b", "c")
            if skip == 2:
                return _make_items("c", "d", "e")  # c is the overlap
            return []

        result = await paginated_fetch(fetch, page_size=page_size)
        ids = [r["id"] for r in result]
        assert ids.count("c") == 1


class TestRightShift:

    async def test_right_shift_extra_overlap(self):
        """Page 2 has N > 1 items overlapping with page 1 (insertions).
        All duplicates skipped, no items missed."""
        page_size = 4

        async def fetch(skip: int, top: int) -> list[dict]:
            if skip == 0:
                return _make_items("a", "b", "c", "d")
            if skip == 3:  # page_size - 1
                # Right-shift: items b, c, d all overlap (3 duplicates instead of 1)
                return _make_items("b", "c", "d", "e")
            return []

        result = await paginated_fetch(fetch, page_size=page_size)
        assert [r["id"] for r in result] == ["a", "b", "c", "d", "e"]


class TestLeftShiftRecovery:

    async def test_left_shift_recovery(self):
        """Page 2's first item is NOT page 1's last item (removals).
        Recovery finds missed items."""
        page_size = 4
        call_count = 0

        async def fetch(skip: int, top: int) -> list[dict]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # page 1: skip=0
                return _make_items("a", "b", "c", "d")
            if call_count == 2:  # page 2: skip=3 — item 'd' was removed
                # 'd' is gone; 'e' (which was after 'd') shifted left
                return _make_items("f", "g", "h", "i")
            if call_count == 3:  # recovery: rewind — should find 'e'
                # Recovery fetches skip=0 or nearby; sees known items + missed 'e'
                return _make_items("a", "b", "c", "e")
            return []

        result = await paginated_fetch(fetch, page_size=page_size)
        ids = [r["id"] for r in result]
        # Must contain all items: a,b,c,d from page 1, e from recovery, f,g,h,i from page 2
        assert "e" in ids, f"Recovery must find missed item 'e', got {ids}"
        # d was collected in page 1, should still be present
        assert "d" in ids

    async def test_left_shift_recovery_multi_page_rewind(self):
        """Left-shift larger than one page. Recovery rewinds multiple times."""
        page_size = 3
        call_count = 0

        async def fetch(skip: int, top: int) -> list[dict]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # page 1: skip=0
                return _make_items("a", "b", "c")
            if call_count == 2:  # page 2: skip=2, overlap expected 'c'
                return _make_items("c", "d", "e")
            if call_count == 3:  # page 3: skip=4, overlap expected 'e'
                # massive left-shift: 'e' is gone, many items removed
                return _make_items("j", "k", "l")
            # Recovery rewind calls:
            if call_count == 4:  # rewind to skip=2 — still no known items?
                return _make_items("g", "h", "i")
            if call_count == 5:  # rewind to skip=0 — finds known items
                return _make_items("a", "b", "f")
            return []

        result = await paginated_fetch(fetch, page_size=page_size)
        ids = [r["id"] for r in result]
        # Must find items from recovery (f, g, h, i) and from page 3 (j, k, l)
        for expected in ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l"]:
            assert expected in ids, f"Expected '{expected}' in results, got {ids}"


class TestFilterAndLimit:

    async def test_filter_fn_applied(self):
        """Only items passing filter_fn appear in results."""

        async def fetch(skip: int, top: int) -> list[dict]:
            if skip == 0:
                return [
                    {"id": "a", "keep": True},
                    {"id": "b", "keep": False},
                    {"id": "c", "keep": True},
                ]
            return []

        result = await paginated_fetch(
            fetch,
            page_size=10,
            filter_fn=lambda item: item.get("keep", False),
        )
        assert [r["id"] for r in result] == ["a", "c"]

    async def test_limit_stops_early(self):
        """With limit=2, pagination stops after collecting 2 filtered results."""
        calls: list[tuple[int, int]] = []

        async def fetch(skip: int, top: int) -> list[dict]:
            calls.append((skip, top))
            # Return a full page every time
            return _make_items(*[f"item-{skip + i}" for i in range(top)])

        result = await paginated_fetch(fetch, page_size=5, limit=2)
        assert len(result) == 2
        # Should have stopped after first page (which has >= 2 items)
        assert len(calls) == 1

    async def test_limit_with_filter_paginates_until_enough(self):
        """With limit + filter, fetches pages until enough filtered results."""
        page_size = 3

        async def fetch(skip: int, top: int) -> list[dict]:
            if skip == 0:
                return [
                    {"id": "a", "match": False},
                    {"id": "b", "match": True},
                    {"id": "c", "match": False},
                ]
            if skip == 2:  # overlap
                return [
                    {"id": "c", "match": False},
                    {"id": "d", "match": True},
                    {"id": "e", "match": False},
                ]
            return []

        result = await paginated_fetch(
            fetch,
            page_size=page_size,
            limit=2,
            filter_fn=lambda item: item.get("match", False),
        )
        assert [r["id"] for r in result] == ["b", "d"]
