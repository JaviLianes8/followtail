"""Byte level line splitting shared by the follower and the last-lines reader."""

from __future__ import annotations

import codecs


def check_encoding(encoding: str) -> None:
    """Reject unknown encodings and those where a newline is not the byte ``\\n``.

    Lines are split on raw bytes before decoding, which is only correct for encodings
    that are ASCII compatible at the newline (UTF-8, Latin-1, cp1252, ...).
    """
    try:
        codecs.lookup(encoding)
    except LookupError:
        raise ValueError(f"unknown encoding: {encoding!r}") from None
    if "\n".encode(encoding) != b"\n" or "\r".encode(encoding) != b"\r":
        raise ValueError(f"encoding {encoding!r} does not encode a newline as the byte \\n")


def split_lines(data: bytes) -> tuple[list[bytes], bytes]:
    """Split ``data`` into complete lines (newline and one trailing ``\\r`` removed).

    Returns the lines and the unterminated remainder, which may be empty.
    """
    parts = data.split(b"\n")
    rest = parts.pop()
    return [part[:-1] if part.endswith(b"\r") else part for part in parts], rest
