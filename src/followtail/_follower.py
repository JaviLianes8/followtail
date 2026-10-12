"""The non-blocking core: a set of watched paths polled one step at a time."""

from __future__ import annotations

import codecs
import os
from collections.abc import Iterable
from types import TracebackType
from typing import Literal

from ._events import Event
from ._text import check_encoding
from ._watch import Start, Watch, WatchOptions

PathArg = str | os.PathLike[str]
Paths = PathArg | Iterable[PathArg]


def _as_paths(paths: Paths) -> list[str]:
    if isinstance(paths, (str, os.PathLike)):
        return [os.fspath(paths)]
    result = [os.fspath(path) for path in paths]
    if not result:
        raise ValueError("at least one path is required")
    return result


def _start(from_start: bool, lines: int | None) -> Start:
    if lines is None:
        return "start" if from_start else "end"
    if isinstance(lines, bool) or not isinstance(lines, int) or lines < 0:
        raise ValueError(f"lines must be an int >= 0, got {lines!r}")
    if from_start:
        raise ValueError("pass either from_start or lines, not both")
    return lines


def _options(
    by: Literal["name", "descriptor"],
    retry: bool,
    partial: Literal["wait", "flush"],
    start: Start,
    encoding: str,
    errors: str,
    max_line: int | None,
) -> WatchOptions:
    if by not in ("name", "descriptor"):
        raise ValueError(f"by must be 'name' or 'descriptor', got {by!r}")
    if partial not in ("wait", "flush"):
        raise ValueError(f"partial must be 'wait' or 'flush', got {partial!r}")
    if max_line is not None and (isinstance(max_line, bool) or max_line < 1):
        raise ValueError(f"max_line must be >= 1, got {max_line!r}")
    check_encoding(encoding)
    try:
        codecs.lookup_error(errors)
    except LookupError:
        raise ValueError(f"unknown error handler: {errors!r}") from None
    return WatchOptions(by, retry, partial, start, encoding, errors, max_line)


class Follower:
    """Follow one or more files, one non-blocking :meth:`poll` at a time.

    This is the engine behind :func:`followtail.follow_events`, for callers that run
    their own loop (a GUI timer, a selector, a test). Each ``poll()`` reads what was
    appended since the previous call, checks for truncation and, when following by name,
    for rotation or deletion, and returns the resulting events in order.

    Arguments mean the same as in :func:`followtail.follow_events`. Use it as a context
    manager, or call :meth:`close`, to release the file descriptors it holds.

    >>> with Follower("app.log", lines=10) as follower:  # doctest: +SKIP
    ...     for event in follower.poll():
    ...         print(event)
    """

    def __init__(
        self,
        paths: Paths,
        *,
        by: Literal["name", "descriptor"] = "name",
        retry: bool = True,
        from_start: bool = False,
        lines: int | None = None,
        partial: Literal["wait", "flush"] = "wait",
        encoding: str = "utf-8",
        errors: str = "strict",
        max_line: int | None = None,
    ) -> None:
        names = _as_paths(paths)
        options = _options(
            by, retry, partial, _start(from_start, lines), encoding, errors, max_line
        )
        self._watches = [Watch(name, options) for name in names]
        self._moved = False

    @property
    def paths(self) -> list[str]:
        """The followed paths, in the order given."""
        return [watch.path for watch in self._watches]

    @property
    def done(self) -> bool:
        """True once every path was dropped (only possible with ``retry=False``)."""
        return all(watch.dropped for watch in self._watches)

    @property
    def moved(self) -> bool:
        """True if the last :meth:`poll` read bytes or produced events."""
        return self._moved

    def poll(self) -> list[Event]:
        """Read every file once and return the new events, oldest first. Never blocks.

        Raises ``UnicodeDecodeError`` for an undecodable line when ``errors="strict"``;
        the bad line is skipped and the next call carries on with the rest.
        """
        events: list[Event] = []
        moved = False
        try:
            for watch in self._watches:
                moved = watch.poll(events) or moved
        finally:
            self._moved = moved or bool(events)
        return events

    def flush(self) -> list[Event]:
        """Return every buffered fragment as an incomplete line, emptying the buffers."""
        events: list[Event] = []
        for watch in self._watches:
            watch.flush(events)
        return events

    def close(self) -> None:
        """Close every held descriptor. Safe to call more than once."""
        for watch in self._watches:
            watch.close()

    def __enter__(self) -> Follower:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
