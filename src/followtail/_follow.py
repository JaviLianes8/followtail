"""Blocking iterators: follow files and yield their lines or typed events."""

from __future__ import annotations

import time
from collections.abc import Callable, Generator
from typing import Literal

from ._events import Event, Line
from ._follower import Follower, PathArg, Paths
from ._pace import Pacer, StopSignal

# Public default poll interval, in seconds, between reads when the file is idle.
DEFAULT_POLL = 0.5


def follow_events(
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
    sleep: Callable[[float], object] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Generator[Event, None, None]:
    """Follow one path or several and yield typed events as they happen.

    Yields :class:`Line` for each new line and, as the files change, :class:`Truncated`,
    :class:`Rotated`, :class:`Missing` and :class:`Appeared`. Every event carries the
    path it belongs to, in the spelling given.

    Tracking (GNU ``tail`` terms):

    - ``by="name"`` (default, ``tail -F``): the name is checked on every poll. When it
      points to a new file (rename and recreate) the old file is read to its end, then
      the new one from its first byte. A deleted file is reported and, with ``retry``,
      picked up again from its first byte once it is recreated.
    - ``by="descriptor"`` (``tail -f``): keep reading the file first opened, even after
      it is renamed or deleted. ``retry`` only matters for that first open.
    - Truncation (``copytruncate``) is detected either way: when a file is shorter than
      the read position, reading resumes from its start.
    - ``retry=False``: a path that cannot be opened is reported once and dropped; the
      iterator ends when no path is left.

    Where to start: at the end (default), at the first byte with ``from_start``, or
    ``lines`` lines before the end (``tail -n``). These apply to files that exist when
    following starts; a file that appears later is always read from its first byte.

    Lines: split on ``\\n``, with the newline and one trailing ``\\r`` removed, decoded
    with ``encoding`` and ``errors`` (``"replace"`` is the safe choice for untrusted
    logs; ``"strict"`` raises ``UnicodeDecodeError``). ``partial="wait"`` holds an
    unterminated fragment until its newline arrives, or until its file is rotated,
    truncated or deleted; ``partial="flush"`` also emits it once the file has been idle
    for a whole poll, and at a stop. Such fragments have ``complete=False``.
    ``max_line`` cuts longer lines into fragments of at most that many bytes.

    Pacing: after a poll that found nothing the iterator waits ``poll`` seconds with
    ``sleep`` (default ``time.sleep``, or ``stop.wait`` when ``stop`` is a
    ``threading.Event``). It ends after ``max_idle`` idle polls in a row, once ``stop``
    is set, or once ``timeout`` seconds have passed on ``clock``; a final poll always
    runs before it ends on a stop or timeout. Otherwise it never ends. Closing the
    generator (or leaving a ``for`` loop) releases the file descriptors.

    Raises ``ValueError`` for invalid settings, ``IsADirectoryError`` for a directory,
    and other ``OSError`` that is not "the file is not there".
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
    return _run(follower, pacer, sleep or pacer.waiter or time.sleep, partial == "flush")


def _run(
    follower: Follower, pacer: Pacer, wait: Callable[[float], object], flush: bool
) -> Generator[Event, None, None]:
    try:
        while not follower.done:
            try:
                events = follower.poll()
            except UnicodeDecodeError:
                yield from follower._take_carried()
                raise
            yield from events
            delay = pacer.next_wait(follower.moved)
            if delay is None:
                break
            if not follower.moved:
                wait(delay)
        if flush:
            yield from follower.flush()
    finally:
        follower.close()


def follow(
    path: PathArg,
    *,
    poll: float = DEFAULT_POLL,
    from_start: bool = False,
    encoding: str = "utf-8",
    max_idle: int | None = None,
    sleep: Callable[[float], object] | None = None,
    by: Literal["name", "descriptor"] = "name",
    retry: bool = True,
    lines: int | None = None,
    partial: Literal["wait", "flush"] = "wait",
    errors: str = "strict",
    max_line: int | None = None,
    stop: StopSignal | None = None,
    timeout: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Generator[str, None, None]:
    """Yield new lines from ``path`` as it grows, like ``tail -F``.

    The simple form of :func:`follow_events` for one file: it yields only the text of
    each line and handles rotation, truncation and deletion silently. Every keyword
    means the same as there. By default it starts at the end of the file, yields a line
    once its newline has arrived, keeps following across log rotation and never returns;
    pass ``max_idle``, ``stop`` or ``timeout`` to make it end.

    >>> for line in follow("/var/log/app.log", lines=10):  # doctest: +SKIP
    ...     print(line)
    """
    events = follow_events(
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


def _texts(events: Generator[Event, None, None]) -> Generator[str, None, None]:
    try:
        for event in events:
            if isinstance(event, Line):
                yield event.text
    finally:
        events.close()
