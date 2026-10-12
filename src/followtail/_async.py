"""Async iterators: the same following, waiting with an awaitable sleep."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import Literal

from ._events import Event, Line
from ._follow import DEFAULT_POLL
from ._follower import Follower, PathArg, Paths
from ._pace import Pacer, StopSignal

AsyncSleep = Callable[[float], Awaitable[object]]


def afollow_events(
    paths: Paths,
    *,
    poll: float = DEFAULT_POLL,
    by: Literal["name", "descriptor"] = "name",
    retry: bool = True,
    from_start: bool = False,
    lines: int | None = None,
    partial: Literal["wait", "flush"] = "wait",
    encoding: str = "utf-8",
    errors: str = "strict",
    max_line: int | None = None,
    max_idle: int | None = None,
    stop: StopSignal | None = None,
    timeout: float | None = None,
    sleep: AsyncSleep | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> AsyncGenerator[Event, None]:
    """Async form of :func:`followtail.follow_events`; every argument means the same.

    Idle waits use ``sleep`` (default ``asyncio.sleep``), so other tasks keep running.
    When ``stop`` is an ``asyncio.Event`` and ``sleep`` is not given, setting it wakes
    the wait at once. Each poll reads local files directly; reads are short and bounded
    (at most 1 MiB per file per poll), so they do not need a thread.

    >>> async for event in afollow_events(["a.log", "b.log"]):  # doctest: +SKIP
    ...     print(event)
    """
    follower = Follower(
        paths,
        by=by,
        retry=retry,
        from_start=from_start,
        lines=lines,
        partial=partial,
        encoding=encoding,
        errors=errors,
        max_line=max_line,
    )
    pacer = Pacer(poll, max_idle, stop, timeout, clock)
    if sleep is None:
        sleep = _event_sleep(stop) if isinstance(stop, asyncio.Event) else asyncio.sleep
    return _run(follower, pacer, sleep, partial == "flush")


def _event_sleep(stop: asyncio.Event) -> AsyncSleep:
    async def sleep(seconds: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), seconds)

    return sleep


async def _run(
    follower: Follower, pacer: Pacer, sleep: AsyncSleep, flush: bool
) -> AsyncGenerator[Event, None]:
    try:
        while not follower.done:
            for event in follower.poll():
                yield event
            delay = pacer.next_wait(follower.moved)
            if delay is None:
                break
            await (asyncio.sleep(0) if follower.moved else sleep(delay))
        if flush:
            for event in follower.flush():
                yield event
    finally:
        follower.close()


def afollow(
    path: PathArg,
    *,
    poll: float = DEFAULT_POLL,
    from_start: bool = False,
    encoding: str = "utf-8",
    max_idle: int | None = None,
    sleep: AsyncSleep | None = None,
    by: Literal["name", "descriptor"] = "name",
    retry: bool = True,
    lines: int | None = None,
    partial: Literal["wait", "flush"] = "wait",
    errors: str = "strict",
    max_line: int | None = None,
    stop: StopSignal | None = None,
    timeout: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> AsyncIterator[str]:
    """Async form of :func:`followtail.follow`: yield the text of each new line.

    >>> async for line in afollow("app.log", timeout=30):  # doctest: +SKIP
    ...     print(line)
    """
    events = afollow_events(
        path,
        poll=poll,
        by=by,
        retry=retry,
        from_start=from_start,
        lines=lines,
        partial=partial,
        encoding=encoding,
        errors=errors,
        max_line=max_line,
        max_idle=max_idle,
        stop=stop,
        timeout=timeout,
        sleep=sleep,
        clock=clock,
    )
    return _texts(events)


async def _texts(events: AsyncGenerator[Event, None]) -> AsyncGenerator[str, None]:
    try:
        async for event in events:
            if isinstance(event, Line):
                yield event.text
    finally:
        await events.aclose()
