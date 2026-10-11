"""Follow a growing text file and yield new complete lines, surviving rotation."""

from __future__ import annotations

import io
import os
import time
from collections.abc import Callable, Iterator

# Public default poll interval, in seconds, between reads when the file is idle.
DEFAULT_POLL = 0.5


class _Tailer:
    """Track one file by name: its identity, read offset and a partial-line buffer.

    Reopening by name on every poll (rather than holding the handle) is what lets a
    rotated file be picked up: a new inode means rename and recreate, a size below the
    remembered offset means truncation. Either way the offset resets to the start.
    """

    def __init__(self, path: str, encoding: str, from_start: bool) -> None:
        self._path = path
        self._encoding = encoding
        self._from_start = from_start
        self._buffer = b""
        self._offset = 0
        self._identity: tuple[int, int] | None = None
        self._primed = False

    def read_new(self) -> list[str]:
        """Return the lines completed since the previous call, or an empty list."""
        try:
            with open(self._path, "rb") as handle:
                data = self._read_from(handle)
        except FileNotFoundError:
            return []
        return self._split(data)

    def _read_from(self, handle: io.BufferedReader) -> bytes:
        status = os.fstat(handle.fileno())
        identity = (status.st_dev, status.st_ino)
        if not self._primed:
            self._primed = True
            self._identity = identity
            self._offset = 0 if self._from_start else status.st_size
        elif identity != self._identity or status.st_size < self._offset:
            self._identity = identity
            self._offset = 0
            self._buffer = b""
        handle.seek(self._offset)
        data = handle.read()
        self._offset = handle.tell()
        return data

    def _split(self, data: bytes) -> list[str]:
        if not data:
            return []
        self._buffer += data
        lines: list[str] = []
        while b"\n" in self._buffer:
            raw, self._buffer = self._buffer.split(b"\n", 1)
            lines.append(raw.rstrip(b"\r").decode(self._encoding))
        return lines


def follow(
    path: str | os.PathLike[str],
    *,
    poll: float = DEFAULT_POLL,
    from_start: bool = False,
    encoding: str = "utf-8",
    max_idle: int | None = None,
    sleep: Callable[[float], object] = time.sleep,
) -> Iterator[str]:
    """Yield new complete lines from ``path`` as it grows, like ``tail -f``.

    The iterator reopens the file on every poll, so it keeps following across log
    rotation: a rename and recreate (new inode) or a truncate (shrunk size) both reset
    the read position to the start of the fresh file. A line is yielded only once its
    terminating newline has arrived, so partial writes are buffered until complete.

    By default it never returns; it blocks on ``sleep(poll)`` while idle. Set
    ``from_start`` to replay the existing content first. For tests, pass ``max_idle`` to
    stop after that many consecutive idle polls, and inject ``sleep`` to avoid real time.
    """
    tailer = _Tailer(os.fspath(path), encoding, from_start)
    idle = 0
    while True:
        lines = tailer.read_new()
        if lines:
            idle = 0
            yield from lines
            continue
        idle += 1
        if max_idle is not None and idle >= max_idle:
            return
        sleep(poll)
