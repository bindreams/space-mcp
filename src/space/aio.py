"""Concurrency helpers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Iterable, Sequence
from typing import Any, TypeVar, overload

logger = logging.getLogger("space.aio")

from .models.enums import StrictModeUnresolved, UnrecognisedApiValue

# Failures that must reach the caller: a strict-mode rejection, or a contract violation.
NEVER_DROPPED: tuple[type[BaseException], ...] = (UnrecognisedApiValue, StrictModeUnresolved, AssertionError)

T = TypeVar("T")
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
    """Await all of `aws` concurrently; on the first failure, cancel and await the rest, then raise one failure.

    A strict-mode rejection or assertion wins over an ordinary failure, then argument order decides; failures during
    the cancellation count too. A child that ends cancelled is a failure, raised as CancelledError when no child
    raised anything else. Every failure not raised is logged at debug. Not a TaskGroup: on Python 3.11 and 3.12 a
    TaskGroup cancels its parent task and never uncancels it, so a later Ctrl-C would leave `asyncio.run` as
    CancelledError.
    """
    return tuple(await gather_all(aws))


async def gather_all(aws: Iterable[Awaitable[T]]) -> list[T]:
    """`gather_cancelling` for any number of awaitables of one type."""
    tasks = [asyncio.ensure_future(aw) for aw in aws]
    pending = set(tasks)
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            if any(_failed(t) for t in done):
                break
    except asyncio.CancelledError:
        await _cancel_and_drain(tasks)
        _log_discarded(tasks, raised=None)
        raise
    if not pending and not any(_failed(t) for t in tasks):
        return [t.result() for t in tasks]
    self_cancelled = any(t.done() and t.cancelled() for t in tasks)
    caller_cancelled = await _cancel_and_drain(tasks)
    chosen = _choose(tasks)
    if caller_cancelled:
        _log_discarded(tasks, raised=None)
        raise asyncio.CancelledError
    _log_discarded(tasks, raised=chosen)
    if chosen is None:
        assert self_cancelled, "a failure was seen, so some child failed or ended cancelled"
        raise asyncio.CancelledError
    exc = chosen.exception()
    assert exc is not None
    raise exc


def _failed(task: asyncio.Future[Any]) -> bool:
    return task.cancelled() or task.exception() is not None


def _choose(tasks: Sequence[asyncio.Future[Any]]) -> asyncio.Future[Any] | None:
    """The failure to raise: a never-dropped one first, then any; argument order within each."""
    raising = [t for t in tasks if not t.cancelled() and t.exception() is not None]
    return next((t for t in raising if isinstance(t.exception(), NEVER_DROPPED)), raising[0] if raising else None)


async def _cancel_and_drain(tasks: Sequence[asyncio.Future[Any]]) -> bool:
    """Cancel the unfinished tasks and wait until all are done; return whether the caller was cancelled meanwhile."""
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
    return caller_cancelled


def _log_discarded(tasks: Sequence[asyncio.Future[Any]], raised: asyncio.Future[Any] | None) -> None:
    """Retrieve and log every failure but the one raised; asyncio.wait retrieves none of them."""
    for task in tasks:
        if task is raised or task.cancelled():
            continue
        exc = task.exception()
        if exc is not None:
            logger.debug("Discarded sibling failure: %r", exc, exc_info=exc)
