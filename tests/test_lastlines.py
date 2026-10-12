"""read_last_lines and the backwards scan, checked against a straightforward reference."""

from __future__ import annotations

import io
import random
from pathlib import Path

import pytest

from followtail import _lastlines as lastlines
from followtail import read_last_lines


def _reference_offset(data: bytes, count: int) -> int:
    """GNU tail -n semantics written the slow, obvious way."""
    if count == 0:
        return len(data)
    starts = [0] + [index + 1 for index, byte in enumerate(data) if byte == 0x0A]
    if starts[-1] == len(data):
        starts.pop()  # a final newline only terminates the last line
    return starts[max(0, len(starts) - count)] if starts else 0


@pytest.mark.parametrize("block", [1, 2, 3, 7, 64 * 1024])
def test_tail_offset_matches_the_reference_on_random_content(
    block: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lastlines, "_BLOCK", block)
    rng = random.Random(block)
    for _ in range(300):
        data = bytes(rng.choice(b"ab\n") for _ in range(rng.randrange(0, 30)))
        for count in range(0, 8):
            got = lastlines.tail_offset(io.BytesIO(data), len(data), count)
            assert got == _reference_offset(data, count), (data, count)


def test_read_last_lines_strips_newlines_and_keeps_an_unterminated_tail(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"one\r\ntwo\nthree")
    assert read_last_lines(log, 2) == ["two", "three"]
    assert read_last_lines(log, 10) == ["one", "two", "three"]
    assert read_last_lines(log, 0) == []


def test_read_last_lines_on_empty_and_newline_only_files(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"")
    assert read_last_lines(log) == []
    log.write_bytes(b"\n\n")
    assert read_last_lines(log, 1) == [""]
    assert read_last_lines(log, 5) == ["", ""]


def test_read_last_lines_decodes_with_the_error_handler(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"ok\n\xff bad\n")
    assert read_last_lines(log, 1, errors="replace") == ["� bad"]
    with pytest.raises(UnicodeDecodeError):
        read_last_lines(log, 1)
    assert read_last_lines(log, 2, encoding="latin-1") == ["ok", "\xff bad"]


def test_read_last_lines_rejects_bad_input(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"x\n")
    with pytest.raises(ValueError, match=">= 0"):
        read_last_lines(log, -1)
    with pytest.raises(ValueError, match="newline"):
        read_last_lines(log, 1, encoding="utf-16")
    with pytest.raises(FileNotFoundError):
        read_last_lines(tmp_path / "missing.log")


def test_read_last_lines_reads_only_the_tail_of_a_large_file(tmp_path: Path) -> None:
    log = tmp_path / "big.log"
    log.write_bytes(b"".join(b"%08d\n" % n for n in range(200_000)))
    assert read_last_lines(log, 3) == ["00199997", "00199998", "00199999"]
