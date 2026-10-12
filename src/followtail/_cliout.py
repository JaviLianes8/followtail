"""Command line output: lines with GNU style file headers, notices on stderr."""

from __future__ import annotations

import os
import sys
from typing import TextIO

from ._events import Appeared, Event, Line, Missing, Rotated, Truncated
from ._watch import IS_A_DIRECTORY

PROG = "followtail"


def warn(message: str) -> None:
    """Print ``followtail: message`` to stderr."""
    print(f"{PROG}: {message}", file=sys.stderr, flush=True)


def is_directory(path: str) -> bool:
    """True for a directory, which GNU ``tail`` reports and skips."""
    return os.path.isdir(path)


class Printer:
    """Write lines to stdout, with ``==> name <==`` headers when the file changes."""

    def __init__(self, headers: bool, out: TextIO | None = None) -> None:
        self._headers = headers
        self._out = out if out is not None else sys.stdout
        self._current: str | None = None
        self._first = True
        self._opened: set[str] = set()
        self.failed: set[str] = set()

    def header(self, path: str) -> None:
        """Print the header for ``path`` unless it was the last one printed."""
        if not self._headers or path == self._current:
            return
        gap = "" if self._first else "\n"
        self._out.write(f"{gap}==> {path} <==\n")
        self._current = path
        self._first = False

    def line(self, path: str, text: str, complete: bool = True) -> None:
        """Print one line of ``path``; a fragment is printed without a newline."""
        self.header(path)
        self._out.write(text + ("\n" if complete else ""))

    def flush(self) -> None:
        """Flush stdout so a reader at the other end of a pipe sees each line."""
        self._out.flush()

    def opened(self, path: str) -> None:
        """Record that ``path`` was read once, so a later loss reads as inaccessible."""
        self._opened.add(path)

    def directory(self, path: str, following: bool) -> None:
        """Report a directory operand the way GNU ``tail`` does."""
        self.header(path)
        self.failed.add(path)
        warn(f"error reading '{path}': {IS_A_DIRECTORY}")
        if following:
            warn(f"{path}: cannot follow end of this type of file")

    def event(self, event: Event) -> None:
        """Print a line, or the GNU ``tail`` notice for any other event."""
        path = event.path
        if isinstance(event, Line):
            self._opened.add(path)
            self.line(path, event.text, event.complete)
        elif isinstance(event, Missing):
            self.failed.add(path)
            if event.reason == IS_A_DIRECTORY:
                self.directory(path, following=True)
            elif path in self._opened:
                warn(f"'{path}' has become inaccessible: {event.reason}")
            else:
                warn(f"cannot open '{path}' for reading: {event.reason}")
        elif isinstance(event, Appeared):
            self._opened.add(path)
            warn(f"'{path}' has appeared;  following new file")
        elif isinstance(event, Rotated):
            warn(f"'{path}' has been replaced;  following new file")
        elif isinstance(event, Truncated):
            warn(f"{path}: file truncated")
