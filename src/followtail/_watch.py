"""Follow one path: hold its descriptor, detect truncation, rotation and deletion."""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Literal

from ._assembler import Assembler
from ._events import Appeared, Event, Missing, Rotated, Truncated
from ._lastlines import tail_offset
from ._open import Identity, identity_of, is_gone, open_shared

_CHUNK = 64 * 1024
# Bytes read per file per poll, so replaying a huge file never loads it at once.
BUDGET = 1024 * 1024

Start = Literal["end", "start"] | int


@dataclass(frozen=True)
class WatchOptions:
    """Validated settings shared by every watched path."""

    by: Literal["name", "descriptor"]
    retry: bool
    partial: Literal["wait", "flush"]
    start: Start
    encoding: str
    errors: str
    max_line: int | None


class Watch:
    """The state of one followed path. ``poll`` never blocks."""

    def __init__(self, path: str, options: WatchOptions) -> None:
        self.path = path
        self.dropped = False
        self._options = options
        self._lines = Assembler(path, options.encoding, options.errors, options.max_line)
        self._handle: io.FileIO | None = None
        self._identity: Identity | None = None
        self._offset = 0
        self._attempted = False
        self._missing = False
        self._stale = False

    def close(self) -> None:
        """Release the descriptor, if one is held."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def flush(self, into: list[Event]) -> None:
        """Append the buffered fragment, if any, to ``into`` as an incomplete line."""
        self._lines.flush()
        self._lines.drain(into)

    def poll(self, into: list[Event]) -> bool:
        """Read what is new, append the events to ``into``, return True if anything moved."""
        before = len(into)
        moved = self._step()
        self._lines.drain(into)
        return moved or len(into) > before

    def _step(self) -> bool:
        if self.dropped:
            return False
        if self._handle is None and not self._open():
            return False
        read = self._read(BUDGET)
        if read >= BUDGET:
            return True
        if self._options.by == "name" and self._name_moved():
            self._read(None)
            self._lines.flush()
            self.close()
            if self._open(replaced=True):
                self._read(BUDGET)
            return True
        return self._settle(read)

    def _settle(self, read: int) -> bool:
        if read or not self._lines.pending:
            self._stale = False
            return read > 0
        if self._options.partial == "flush" and self._stale:
            self._lines.flush()
            self._stale = False
            return True
        self._stale = True
        return False

    def _open(self, replaced: bool = False) -> bool:
        first = not self._attempted
        self._attempted = True
        try:
            if os.path.isdir(self.path):
                raise IsADirectoryError(f"is a directory: {self.path!r}")
            handle = open_shared(self.path)
        except IsADirectoryError:
            raise
        except OSError as error:
            if not is_gone(error):
                raise
            self._gone(first)
            return False
        status = os.fstat(handle.fileno())
        self._handle = handle
        self._identity = identity_of(status)
        if first:
            self._offset = self._initial_offset(handle, status.st_size)
        else:
            self._offset = 0
            self._lines.event(Rotated(self.path) if replaced else Appeared(self.path))
        self._missing = False
        return True

    def _gone(self, first: bool) -> None:
        if not self._missing:
            self._missing = True
            self._lines.event(Missing(self.path))
        if not self._options.retry and (first or self._options.by == "name"):
            self.dropped = True

    def _initial_offset(self, handle: io.FileIO, size: int) -> int:
        start = self._options.start
        if start == "end":
            return size
        if start == "start":
            return 0
        return tail_offset(handle, size, start)

    def _read(self, budget: int | None) -> int:
        handle = self._handle
        if handle is None:
            return 0
        if os.fstat(handle.fileno()).st_size < self._offset:
            self._lines.flush()
            self._lines.event(Truncated(self.path))
            self._offset = 0
        handle.seek(self._offset)
        total = 0
        while budget is None or total < budget:
            size = _CHUNK if budget is None else min(_CHUNK, budget - total)
            chunk = handle.read(size)
            if not chunk:
                break
            total += len(chunk)
            self._lines.feed(chunk)
        self._offset += total
        return total

    def _name_moved(self) -> bool:
        try:
            status = os.stat(self.path)
        except OSError as error:
            if not is_gone(error):
                raise
            return True
        return identity_of(status) != self._identity
