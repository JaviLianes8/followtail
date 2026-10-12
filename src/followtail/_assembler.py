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
        # A bytearray, so a long line arriving in many chunks is appended in place
        # instead of being copied again for every chunk.
        self._buffer = bytearray()
        self._queue: deque[_Item] = deque()

    @property
    def pending(self) -> bool:
        """True while an unterminated fragment is buffered."""
        return bool(self._buffer)

    def feed(self, chunk: bytes) -> None:
        """Append ``chunk`` and queue every line it completes."""
        if b"\n" not in chunk:
            self._buffer += chunk
            self._buffer = self._cut(self._buffer, final=False)
            return
        lines, rest = split_lines(bytes(self._buffer) + chunk)
        for raw in lines:
            self._queue.append((bytes(self._cut(bytearray(raw), final=True)), True))
        self._buffer = self._cut(bytearray(rest), final=False)

    def flush(self) -> None:
        """Queue the buffered fragment, if any, as an incomplete line."""
        if self._buffer:
            self._queue.append((bytes(self._buffer), False))
            self._buffer = bytearray()

    def event(self, event: Event) -> None:
        """Queue a non-line event after the lines already queued."""
        self._queue.append(event)

    def drain(self, into: list[Event]) -> None:
        """Move queued items into ``into``, decoding lines on the way.

        A ``UnicodeDecodeError`` (with ``errors="strict"``) propagates after the bad
        line has been dropped; the items moved before it stay in ``into`` and the rest
        of the queue is kept for the next call.
        """
        while self._queue:
            item = self._queue.popleft()
            if isinstance(item, tuple):
                raw, complete = item
                item = Line(self._path, raw.decode(self._encoding, self._errors), complete)
            into.append(item)

    def _cut(self, data: bytearray, final: bool) -> bytearray:
        """Queue ``max_line`` sized fragments off the front of ``data``; return the rest.

        A carriage return at the very end of an unterminated buffer does not count, as
        it may be the first half of a CRLF still being written.
        """
        limit = self._max_line
        if limit is None:
            return data
        size = len(data) - (0 if final or not data.endswith(b"\r") else 1)
        start = 0
        while size - start > limit:
            cut = start + limit
            if self._utf8:
                # Never split a UTF-8 sequence: back off over continuation bytes.
                while cut > start + limit - 3 and data[cut] & 0xC0 == 0x80:
                    cut -= 1
            self._queue.append((bytes(data[start:cut]), False))
            start = cut
        return data[start:] if start else data
