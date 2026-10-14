"""gather_cancelling: siblings never outlive a failure, and every failure is retrieved."""

import asyncio
import gc
import logging

import pytest

from space.aio import gather_cancelling


async def _value(value):
    return value


async def _fail(exc: BaseException):
    raise exc


async def _blocked(record: list[str]) -> None:
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        record.append("cancelled")
        raise


def _asyncio_errors(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "asyncio" and r.levelno >= logging.ERROR]


def _discarded(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "space.aio"]


async def test_results_keep_argument_order():
    assert await gather_cancelling(_value(1), _value("a")) == (1, "a")
    assert await gather_cancelling(_value(1), _value(2), _value(3)) == (1, 2, 3)


async def test_first_failure_is_raised_as_itself():
    with pytest.raises(ValueError, match="boom"):
        await gather_cancelling(_fail(ValueError("boom")), _value(1))


async def test_sibling_is_cancelled_before_the_failure_leaves():
    record: list[str] = []
    with pytest.raises(ValueError):
        await gather_cancelling(_fail(ValueError("x")), _blocked(record))
    assert record == ["cancelled"]


async def test_failure_leaves_the_caller_uncancelled():
    record: list[str] = []
    with pytest.raises(ValueError):
        await gather_cancelling(_fail(ValueError("x")), _blocked(record))
    task = asyncio.current_task()
    assert task is not None and task.cancelling() == 0


async def test_same_step_sibling_failure_is_retrieved_and_logged(caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ValueError, match="first"):
        await gather_cancelling(_fail(ValueError("first")), _fail(ValueError("second")))
    gc.collect()
    assert _asyncio_errors(caplog) == []
    (record, ) = _discarded(caplog)
    assert record.levelno == logging.DEBUG
    assert record.exc_info is not None and str(record.exc_info[1]) == "second"


async def test_drain_time_failure_is_retrieved_and_logged(caplog):
    caplog.set_level(logging.DEBUG)

    async def late():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise RuntimeError("late")

    with pytest.raises(ValueError, match="first"):
        await gather_cancelling(_fail(ValueError("first")), late())
    gc.collect()
    assert _asyncio_errors(caplog) == []
    (record, ) = _discarded(caplog)
    assert record.exc_info is not None and str(record.exc_info[1]) == "late"


@pytest.mark.parametrize("case", ["release", "cancel-again", "late-failure"])
async def test_caller_cancellation_drains_the_children(caplog, case):
    caplog.set_level(logging.DEBUG)
    record: list[str] = []
    release = asyncio.Event()
    started = [asyncio.Event(), asyncio.Event()]
    seen = [asyncio.Event(), asyncio.Event()]

    async def child(i: int) -> None:
        started[i].set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            record.append("cancelled")
            seen[i].set()
            await release.wait()
            if case == "late-failure":
                raise RuntimeError(f"late {i}")
            raise

    outer = asyncio.ensure_future(gather_cancelling(child(0), child(1)))
    for event in started:
        await event.wait()
    outer.cancel()
    for event in seen:
        await event.wait()
    assert not outer.done()
    if case == "cancel-again":
        outer.cancel()
    else:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await outer
    assert record == ["cancelled", "cancelled"]
    gc.collect()
    assert _asyncio_errors(caplog) == []
    if case == "late-failure":
        assert sorted(str(r.exc_info[1]) for r in _discarded(caplog) if r.exc_info) == ["late 0", "late 1"]
    else:
        assert _discarded(caplog) == []


async def test_child_that_swallows_the_cancel_and_returns(caplog):
    caplog.set_level(logging.DEBUG)

    async def stubborn():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return "ignored"

    with pytest.raises(ValueError, match="x"):
        await gather_cancelling(_fail(ValueError("x")), stubborn())
    assert _discarded(caplog) == []


async def test_self_cancelled_child_raises_cancelled_error():
    with pytest.raises(asyncio.CancelledError):
        await gather_cancelling(_fail(asyncio.CancelledError()), _value(1))
