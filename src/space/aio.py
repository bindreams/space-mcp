"""Concurrency helpers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Sequence
from typing import Any, TypeVar, overload

logger = logging.getLogger("space.aio")

A = TypeVar("A")
B = TypeVar("B")
C = TypeVar("C")


@overload
async def gather_cancelling(a: Awaitable[A], b: Awaitable[B], /) -> tuple[A, B]:
    ...


@overload
async def gather_cancelling(a: Awaitable[A], b: Awaitable[B], c: Awaitable[C], /) -> tuple[A, B, C]:
    ...


async def gather_cancelling(*aws: Awaitable[Any]) -> tuple[Any, ...]:
    """Await all of `aws` concurrently; on the first failure, cancel and await the rest before raising it.

    Raises the first failure in argument order, unwrapped. Not a TaskGroup: on Python 3.11 and 3.12 a TaskGroup cancels
    its parent task and never uncancels it, so a later Ctrl-C would leave `asyncio.run` as CancelledError.
    """
    tasks = [asyncio.ensure_future(aw) for aw in aws]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    except asyncio.CancelledError:
        await _cancel_and_drain(tasks, raised=None)
        raise
    failed = next((t for t in tasks if t.done() and not t.cancelled() and t.exception() is not None), None)
    if failed is None:
        return tuple(t.result() for t in tasks)
    await _cancel_and_drain(tasks, raised=failed)
    exc = failed.exception()
    assert exc is not None
    raise exc


async def _cancel_and_drain(tasks: Sequence[asyncio.Future[Any]], raised: asyncio.Future[Any] | None) -> None:
    """Cancel the unfinished tasks and wait until all are done; re-raise a cancellation of the caller afterwards."""
    caller_cancelled = False
    for task in tasks:
        if not task.done():  # cancel() on a done task would also silence its unretrieved exception
            task.cancel()
    while pending := [t for t in tasks if not t.done()]:
        try:
            await asyncio.wait(pending)
        except asyncio.CancelledError:
            caller_cancelled = True
            for task in pending:
                task.cancel()
    # asyncio.wait(FIRST_EXCEPTION) retrieves every failed completion but the last, and ALL_COMPLETED retrieves none
    for task in tasks:
        if task is raised or task.cancelled():
            continue
        exc = task.exception()
        if exc is not None:
            logger.debug("Discarded sibling failure: %r", exc, exc_info=exc)
    if caller_cancelled:
        raise asyncio.CancelledError
