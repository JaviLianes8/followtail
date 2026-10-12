"""Command line modes: print the end of files once, or keep following them."""

from __future__ import annotations

import argparse
import io
import os
import time
from collections.abc import Iterator
from typing import Literal

from ._cliout import Printer, is_directory, warn
from ._events import Appeared, Event, Line, Missing, Rotated, Truncated
from ._follower import Follower
from ._lastlines import tail_offset
from ._open import open_shared, unavailable
from ._pace import Pacer

# The clock and the wait between idle polls, looked up at call time so tests can
# replace them.
_clock = time.monotonic
_sleep = time.sleep


def _lines_of(path: str, from_line: bool, count: int) -> Iterator[tuple[bytes, bool]]:
    """Stream the selected lines of ``path`` as (bytes without newline, terminated)."""
    with open_shared(path) as raw:
        size = os.fstat(raw.fileno()).st_size
        raw.seek(0 if from_line else tail_offset(raw, size, count))
        skip = max(count, 1) - 1 if from_line else 0
        for line in io.BufferedReader(raw):
            if skip:
                skip -= 1
            elif line.endswith(b"\n"):
                yield line[:-2] if line.endswith(b"\r\n") else line[:-1], True
            else:
                yield line, False


def print_once(args: argparse.Namespace, printer: Printer) -> int:
    """``tail -n``: print the selected lines of every file and return the status."""
    from_line, count = args.lines
    for path in args.files:
        if is_directory(path):
            printer.directory(path, following=False)
            continue
        try:
            lines = _lines_of(path, from_line, count)
            first = next(lines, None)
        except OSError as exc:
            warn(f"cannot open '{path}' for reading: {unavailable(exc) or exc.strerror or exc}")
            printer.failed.add(path)
            continue
        printer.header(path)
        while first is not None:
            raw, complete = first
            printer.line(path, raw.decode(args.encoding, args.errors), complete)
            first = next(lines, None)
    return 1 if printer.failed else 0


def follow(args: argparse.Namespace, printer: Printer) -> int:
    """``tail -f`` / ``tail -F``: print as files grow until stopped; return the status."""
    from_line, count = args.lines
    by: Literal["name", "descriptor"] = "descriptor" if args.follow == "descriptor" else "name"
    retry = args.retry or args.follow == "name-retry"
    paths = [path for path in args.files if not is_directory(path)]
    if not paths:
        for path in args.files:
            printer.directory(path, following=True)
        warn("no files remaining")
        return 1
    skip = {path: max(count, 1) - 1 if from_line else 0 for path in paths}

    def show(event: Event) -> None:
        if isinstance(event, (Rotated, Truncated, Appeared)):
            skip[event.path] = 0
        elif isinstance(event, Line) and event.complete and skip[event.path] > 0:
            skip[event.path] -= 1
            return
        printer.event(event)

    pacer = Pacer(args.sleep_interval, None, None, args.timeout, _clock)
    with Follower(paths, by=by, retry=retry, from_start=from_line,
                  lines=None if from_line else count, partial=args.partial,
                  encoding=args.encoding, errors=args.errors) as follower:  # fmt: skip
        first = follower.poll()
        for path in dict.fromkeys(args.files):  # like GNU tail: header, then first lines
            if path not in paths:
                printer.directory(path, following=True)
                continue
            own = [event for event in first if event.path == path]
            if not any(isinstance(event, Missing) for event in own):
                printer.opened(path)
                printer.header(path)
            for event in own:
                show(event)
        while True:
            printer.flush()
            delay = None if follower.done else pacer.next_wait(follower.moved)
            if delay is None:
                break
            if not follower.moved:
                _sleep(delay)
            for event in follower.poll():
                show(event)
        for event in follower.flush() if args.partial == "flush" else []:
            show(event)
    if follower.done:
        warn("no files remaining")
    return 1 if len(paths) < len(args.files) or (printer.failed and not retry) else 0
