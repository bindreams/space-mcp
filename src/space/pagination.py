"""Overlap-based paginated fetch with consistency verification.

Uses 1-item overlap between consecutive pages to detect and recover from
concurrent modifications to the underlying data:

- Normal: last item of page N == first item of page N+1 (expected overlap of 1)
- Right-shift (insertions): more overlap items → deduplicated automatically
- Left-shift (removals): no overlap → recovery via backward scan
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

_PAGE_SIZE = 10_000


async def paginated_fetch(
    fetch_page: Callable[[int, int], Awaitable[list[dict]]],
    *,
    page_size: int | None = None,
    filter_fn: Callable[[dict], bool] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Paginate through API results with overlap-based consistency.

    Args:
        fetch_page: async fn(skip, top) -> list[dict], each dict must have 'id'
        page_size: items per request (defaults to _PAGE_SIZE module constant)
        filter_fn: optional client-side filter (applied per item)
        limit: stop after collecting this many filtered results

    Returns:
        Deduplicated, filtered results in API order, up to limit.
    """
    if page_size is None:
        page_size = _PAGE_SIZE
    seen_ids: set[str] = set()
    results: list[dict] = []
    skip = 0
    prev_tail_id: str | None = None

    while True:
        if limit is not None and len(results) >= limit:
            break

        page = await fetch_page(skip, page_size)
        if not page:
            break

        new_items = _stitch_page(page, prev_tail_id, seen_ids)

        if new_items is None:
            # Left-shift detected — recover missed items
            recovered = await _recover_gap(
                fetch_page, page_size, skip, seen_ids,
            )
            _collect(recovered, seen_ids, results, filter_fn, limit)
            # Also process the current page for unseen items
            new_items = [item for item in page if item["id"] not in seen_ids]

        _collect(new_items, seen_ids, results, filter_fn, limit)

        raw_page_len = len(page)
        if raw_page_len < page_size:
            break  # last page

        prev_tail_id = page[-1]["id"]
        skip += page_size - 1  # advance with 1-item overlap

    return results


def _stitch_page(
    page: list[dict],
    prev_tail_id: str | None,
    seen_ids: set[str],
) -> list[dict] | None:
    """Verify page stitching with the previous page.

    Returns:
        list of new items (after removing overlap), or
        None if left-shift detected (overlap item missing).
    """
    if prev_tail_id is None:
        return page  # first page, no stitching

    # Search for the overlap item in this page
    for i, item in enumerate(page):
        if item["id"] == prev_tail_id:
            # Found overlap at position i. Items 0..i are overlap (already seen).
            return page[i + 1 :]

    # Overlap item not found — left-shift detected
    return None


async def _recover_gap(
    fetch_page: Callable[[int, int], Awaitable[list[dict]]],
    page_size: int,
    current_skip: int,
    seen_ids: set[str],
) -> list[dict]:
    """Recover missed items after left-shift detection.

    Rewinds backward page by page until finding a page with at least one
    already-seen item (confirming continuity). Collects all unseen items
    along the way — these are the items missed due to the shift.
    """
    missed: list[dict] = []
    recovery_seen: set[str] = set(seen_ids)  # track ids within recovery to avoid duplicates
    recovery_skip = max(0, current_skip - page_size + 1)

    while True:
        page = await fetch_page(recovery_skip, page_size)
        if not page:
            break

        has_known_item = any(item["id"] in seen_ids for item in page)
        new_items = [item for item in page if item["id"] not in recovery_seen]
        for item in new_items:
            recovery_seen.add(item["id"])
        missed.extend(new_items)

        if has_known_item:
            break  # found continuity with previously seen data

        if recovery_skip == 0:
            break  # can't go further back

        recovery_skip = max(0, recovery_skip - page_size + 1)

    return missed


def _collect(
    items: list[dict],
    seen_ids: set[str],
    results: list[dict],
    filter_fn: Callable[[dict], bool] | None,
    limit: int | None,
) -> None:
    """Add unseen, filtered items to results (mutates seen_ids and results)."""
    for item in items:
        if limit is not None and len(results) >= limit:
            return

        item_id = item["id"]
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        if filter_fn is not None and not filter_fn(item):
            continue

        results.append(item)
