"""Find where the last N lines of a file start, reading backwards from its end."""

from __future__ import annotations

import os
from typing import BinaryIO

from ._open import open_shared
from ._text import check_encoding, split_lines

_BLOCK = 64 * 1024


def tail_offset(handle: BinaryIO, size: int, count: int) -> int:
    """Byte offset where the last ``count`` lines of the first ``size`` bytes begin.

    As in GNU ``tail -n``, an unterminated last line counts as a line, and a newline
    in the very last byte only terminates the last line.
    """
    if count < 0:
        raise ValueError(f"line count must be >= 0, got {count}")
    if count == 0 or size == 0:
        return size
    end = size
    handle.seek(size - 1)
    if handle.read(1) == b"\n":
        end = size - 1
    seen = 0
    position = end
    while position > 0:
        start = max(0, position - _BLOCK)
        handle.seek(start)
        block = handle.read(position - start)
        index = len(block)
        while True:
            index = block.rfind(b"\n", 0, index)
            if index < 0:
                break
            seen += 1
            if seen == count:
                return start + index + 1
        position = start
    return 0


def read_last_lines(
    path: str | os.PathLike[str],
    count: int = 10,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> list[str]:
    """Return the last ``count`` lines of ``path``, like ``tail -n count`` without ``-f``.

    Lines come without their newline and trailing ``\\r``. An unterminated last line is
    included. The file is read backwards in blocks, so a huge log costs only the bytes
    of the lines returned. Raises ``FileNotFoundError`` if the file does not exist and
    ``ValueError`` for a negative ``count`` or an encoding that does not encode a
    newline as the single byte ``\\n``.
    """
    check_encoding(encoding)
    with open_shared(os.fspath(path)) as handle:
        size = os.fstat(handle.fileno()).st_size
        offset = tail_offset(handle, size, count)
        handle.seek(offset)
        data = handle.read(size - offset) or b""
    lines, rest = split_lines(data)
    if rest:
        lines.append(rest)
    return [raw.decode(encoding, errors) for raw in lines]
