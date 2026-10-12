"""Follower: options, decoding, buffering limits and the per-poll read budget."""

from __future__ import annotations

from pathlib import Path

import pytest

from followtail import Event, Follower, Line, Missing, follow
from followtail import _watch as watch


def _lines(path: Path, *texts: str, complete: bool = True) -> list[Line]:
    return [Line(str(path), text, complete) for text in texts]


def test_paths_accepts_one_path_or_several(tmp_path: Path) -> None:
    assert Follower(tmp_path / "a").paths == [str(tmp_path / "a")]
    assert Follower([tmp_path / "a", str(tmp_path / "b")]).paths == [
        str(tmp_path / "a"),
        str(tmp_path / "b"),
    ]
    assert Follower(p for p in ["x.log"]).paths == ["x.log"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"by": "inode"}, "by must be"),
        ({"partial": "never"}, "partial must be"),
        ({"lines": -1}, "lines must be"),
        ({"lines": True}, "lines must be"),
        ({"lines": 3, "from_start": True}, "either from_start or lines"),
        ({"max_line": 0}, "max_line must be"),
        ({"max_line": 3}, "max_line must be >= 4"),
        ({"encoding": "utf-16"}, "newline"),
        ({"encoding": "no-such-codec"}, "unknown encoding"),
        ({"errors": "no-such-handler"}, "unknown error handler"),
    ],
)
def test_invalid_options_are_rejected_up_front(
    tmp_path: Path, kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        Follower(tmp_path / "a.log", **kwargs)  # type: ignore[arg-type]


def test_an_empty_path_list_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one path"):
        Follower([])


def test_a_directory_raises_instead_of_waiting_forever(tmp_path: Path) -> None:
    with pytest.raises(IsADirectoryError), Follower(tmp_path) as follower:
        follower.poll()


def test_strict_decoding_loses_only_the_bad_line(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"good\n\xff\xfe\nafter\n")
    with Follower(log, from_start=True) as follower:
        with pytest.raises(UnicodeDecodeError):
            follower.poll()
        assert follower.poll() == _lines(log, "good", "after")


def test_a_decode_error_in_one_file_keeps_the_lines_of_the_others(tmp_path: Path) -> None:
    first, second = tmp_path / "b.log", tmp_path / "a.log"
    first.write_bytes(b"")
    second.write_bytes(b"")
    with Follower([first, second]) as follower:
        follower.poll()
        first.write_bytes(b"from b\n")
        second.write_bytes(b"\xff\n")
        with pytest.raises(UnicodeDecodeError):
            follower.poll()
        assert follower.poll() == [Line(str(first), "from b")]


def test_the_iterator_yields_what_came_before_a_decode_error(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"one\ntwo\n\xff\n")
    seen: list[str] = []
    with pytest.raises(UnicodeDecodeError):
        for line in follow(log, from_start=True, max_idle=1, poll=0):
            seen.append(line)
    assert seen == ["one", "two"]


def test_replace_decoding_never_raises(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"caf\xc3\xa9 \xff\n")
    with Follower(log, from_start=True, errors="replace") as follower:
        assert follower.poll() == _lines(log, "café �")


def test_lines_are_decoded_whole_even_when_a_character_spans_two_reads(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"\xe2\x82")
    with Follower(log, from_start=True) as follower:
        assert follower.poll() == []
        with open(log, "ab") as handle:
            handle.write(b"\xac euro\n")
        assert follower.poll() == _lines(log, "€ euro")


def test_max_line_cuts_long_lines_on_utf8_boundaries(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes("ab€€cd\n".encode())
    with Follower(log, from_start=True, max_line=4) as follower:
        assert follower.poll() == [
            Line(str(log), "ab", complete=False),
            Line(str(log), "€", complete=False),
            Line(str(log), "€c", complete=False),
            Line(str(log), "d"),
        ]


def test_flush_returns_the_buffered_fragment(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"done\npending")
    with Follower(log, from_start=True) as follower:
        assert follower.poll() == _lines(log, "done")
        assert follower.flush() == _lines(log, "pending", complete=False)
        assert follower.flush() == []


def test_a_huge_backlog_is_read_in_bounded_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(watch, "BUDGET", 10)
    log = tmp_path / "a.log"
    log.write_bytes(b"0123\n" * 5)
    with Follower(log, from_start=True) as follower:
        first = follower.poll()
        assert len(first) == 2 and follower.moved
        rest = follower.poll() + follower.poll()
        assert [line.text for line in first + rest] == ["0123"] * 5  # type: ignore[union-attr]


def test_moved_is_false_after_an_idle_poll(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"x\n")
    with Follower(log) as follower:
        follower.poll()
        assert not follower.moved
        assert not follower.done


def test_close_is_idempotent_and_a_closed_follower_refuses_to_poll(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"")
    follower = Follower(log)
    follower.poll()
    follower.close()
    follower.close()
    with pytest.raises(ValueError, match="closed"):
        follower.poll()


def test_a_trailing_carriage_return_is_not_cut_from_its_newline(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"abcd\r")
    with Follower(log, from_start=True, max_line=4) as follower:
        assert follower.poll() == []
        with open(log, "ab") as handle:
            handle.write(b"\nefghij\n")
        assert follower.poll() == [
            Line(str(log), "abcd"),
            Line(str(log), "efgh", complete=False),
            Line(str(log), "ij"),
        ]


def test_a_huge_unterminated_line_is_buffered_in_linear_time(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"x" * (48 * 1024 * 1024) + b"\n")
    with Follower(log, from_start=True) as follower:
        events: list[Event] = []
        while not events:
            events = follower.poll()
    assert events == [Line(str(log), "x" * (48 * 1024 * 1024))]


def test_a_path_that_becomes_a_directory_is_dropped(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"")
    with Follower(log) as follower:
        follower.poll()
        log.unlink()
        log.mkdir()
        assert follower.poll() == [Missing(str(log), "Is a directory")]
        assert follower.done
