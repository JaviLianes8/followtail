"""Turn raw byte chunks into typed events, keeping order and surviving decode errors."""

from __future__ import annotations

import codecs
from collections import deque

from ._events import Event, Line
from ._text import split_lines

# A queued line is kept as raw bytes until it is handed out, so a decode error raised
# for one line leaves every later line and event queued for the next call.
_Item = Event | tuple[bytes, bool]


class Assembler:
    """Collect complete lines from chunks of one file and queue them with its events."""

    def __init__(self, path: str, encoding: str, errors: str, max_line: int | None) -> None:
        self._path = path
        self._encoding = encoding
        self._errors = errors
        self._max_line = max_line
        self._utf8 = codecs.lookup(encoding).name == "utf-8"
        self._buffer = b""
        self._queue: deque[_Item] = deque()

    @property
    def pending(self) -> bool:
        """True while an unterminated fragment is buffered."""
        return bool(self._buffer)

    def feed(self, chunk: bytes) -> None:
        """Append ``chunk`` and queue every line it completes."""
        lines, rest = split_lines(self._buffer + chunk)
        for raw in lines:
            self._queue.append((self._cut(raw), True))
        self._buffer = self._cut(rest)

    def flush(self) -> None:
        """Queue the buffered fragment, if any, as an incomplete line."""
        if self._buffer:
            self._queue.append((self._buffer, False))
            self._buffer = b""

    def event(self, event: Event) -> None:
        """Queue a non-line event after the lines already queued."""
        self._queue.append(event)

    def drain(self, into: list[Event]) -> None:
        """Move queued items into ``into``, decoding lines on the way.

        A ``UnicodeDecodeError`` (with ``errors="strict"``) propagates after the bad
        line has been dropped; the rest of the queue is kept for the next call.
        """
        while self._queue:
            item = self._queue.popleft()
            if isinstance(item, tuple):
                raw, complete = item
                item = Line(self._path, raw.decode(self._encoding, self._errors), complete)
            into.append(item)

    def _cut(self, data: bytes) -> bytes:
        """Queue ``max_line`` sized fragments off the front of ``data``; return the rest."""
        limit = self._max_line
        while limit is not None and len(data) > limit:
            cut = limit
            if self._utf8:
                # Never split a UTF-8 sequence: back off over continuation bytes.
                while cut > limit - 3 and cut > 1 and data[cut] & 0xC0 == 0x80:
                    cut -= 1
            self._queue.append((data[:cut], False))
            data = data[cut:]
        return data
