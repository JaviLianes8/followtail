"""Real filesystem, real writer process: appends, partial lines, start positions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from conftest import Writer, poll_until, texts

from followtail import Appeared, Follower, Line, Missing


def test_lines_appended_by_another_process_arrive_in_order(
    tmp_path: Path, writer_for: Callable[[Path], Writer]
) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"before\n")
    writer = writer_for(log)
    with Follower(log) as follower:
        assert follower.poll() == []
        writer.write("one\ntwo\n")
        writer.write("three\n")
        events = poll_until(follower, lambda got: len(got) >= 3)
    assert events == [Line(str(log), "one"), Line(str(log), "two"), Line(str(log), "three")]


def test_a_partial_line_is_held_until_its_newline_is_written(
    tmp_path: Path, writer_for: Callable[[Path], Writer]
) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"")
    writer = writer_for(log)
    with Follower(log) as follower:
        follower.poll()
        writer.write("half")
        assert [follower.poll() for _ in range(5)] == [[]] * 5
        writer.write(" and the rest\n")
        events = poll_until(follower, lambda got: bool(got))
    assert events == [Line(str(log), "half and the rest")]


def test_partial_flush_emits_a_fragment_left_idle_for_one_poll(
    tmp_path: Path, writer_for: Callable[[Path], Writer]
) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"")
    writer = writer_for(log)
    with Follower(log, partial="flush") as follower:
        follower.poll()
        writer.write("prompt> ")
        assert follower.poll() == []  # read, not yet idle
        assert follower.poll() == []  # first idle poll: give the writer a chance
        assert follower.poll() == [Line(str(log), "prompt> ", complete=False)]
        writer.write("answer\n")
        events = poll_until(follower, lambda got: bool(got))
    assert events == [Line(str(log), "answer")]


def test_last_n_lines_then_new_ones(tmp_path: Path, writer_for: Callable[[Path], Writer]) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"".join(b"line %d\n" % n for n in range(1, 101)))
    writer = writer_for(log)
    with Follower(log, lines=3) as follower:
        events = poll_until(follower, lambda got: len(got) >= 3)
        writer.write("line 101\n")
        poll_until(follower, lambda got: len(got) >= 4, events)
    assert texts(events) == ["line 98", "line 99", "line 100", "line 101"]


def test_a_file_created_after_following_started_is_read_from_its_first_byte(
    tmp_path: Path, writer_for: Callable[[Path], Writer]
) -> None:
    log = tmp_path / "late.log"
    with Follower(log) as follower:
        assert follower.poll() == [Missing(str(log))]
        assert follower.poll() == []  # reported once
        writer_for(log).write("first\nsecond\n")
        events = poll_until(follower, lambda got: len(got) >= 3)
    assert events == [Appeared(str(log)), Line(str(log), "first"), Line(str(log), "second")]


def test_a_free_running_writer_loses_and_repeats_nothing(
    tmp_path: Path, writer_for: Callable[[Path], Writer]
) -> None:
    log = tmp_path / "busy.log"
    log.write_bytes(b"")
    writer = writer_for(log)
    with Follower(log) as follower:
        follower.poll()
        writer.send("burst", wait=False, prefix="n", start=0, count=3000, pause=0)
        events = poll_until(follower, lambda got: len(got) >= 3000)
        writer.ack()
        assert follower.poll() == []
    assert texts(events) == [f"n{number}" for number in range(3000)]
    assert all(isinstance(event, Line) and event.complete for event in events)


def test_several_files_report_their_own_path(
    tmp_path: Path, writer_for: Callable[[Path], Writer]
) -> None:
    first, second = tmp_path / "a.log", tmp_path / "b.log"
    first.write_bytes(b"")
    second.write_bytes(b"")
    with Follower([first, second]) as follower:
        follower.poll()
        writer_for(second).write("from b\n")
        writer_for(first).write("from a\n")
        events = poll_until(follower, lambda got: len(got) >= 2)
    assert sorted(events, key=lambda event: event.path) == [
        Line(str(first), "from a"),
        Line(str(second), "from b"),
    ]
