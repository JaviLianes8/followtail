"""Real filesystem, real writer process: every rotation style logrotate can perform."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import Writer, poll_until, texts

from followtail import Appeared, Event, Follower, Line, Missing, Rotated, Truncated


def test_create_rotation_drains_the_old_file_before_switching(
    tmp_path: Path, writer_for: Callable[[Path], Writer]
) -> None:
    log, old = tmp_path / "app.log", tmp_path / "app.log.1"
    log.write_bytes(b"")
    writer = writer_for(log)
    with Follower(log) as follower:
        follower.poll()
        writer.write("one\n")
        poll_until(follower, lambda got: bool(got))
        writer.write("two\n")  # appended, but not polled before the rotation
        writer.send("close")
        log.rename(old)
        writer.write("three\n")  # the writer reopens the name: a new file
        events = poll_until(follower, lambda got: len(got) >= 3)
    path = str(log)
    assert events == [Line(path, "two"), Rotated(path), Line(path, "three")]
    assert old.read_bytes() == b"one\ntwo\n"


@pytest.mark.skipif(sys.platform == "win32", reason="Windows writers cannot be renamed while open")
def test_lines_written_to_the_old_descriptor_after_a_rename_are_not_lost(
    tmp_path: Path, writer_for: Callable[[Path], Writer]
) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"")
    writer = writer_for(log)
    with Follower(log) as follower:
        follower.poll()
        log.rename(tmp_path / "app.log.1")
        writer.write("late\n")  # still holding the old file
        log.write_bytes(b"fresh\n")
        events = poll_until(follower, lambda got: len(got) >= 3)
    assert events == [Line(str(log), "late"), Rotated(str(log)), Line(str(log), "fresh")]


def test_copytruncate_rotation_is_reported_and_followed(
    tmp_path: Path, writer_for: Callable[[Path], Writer]
) -> None:
    log, copy = tmp_path / "app.log", tmp_path / "app.log.1"
    log.write_bytes(b"")
    writer = writer_for(log)  # keeps its descriptor open, as copytruncate assumes
    with Follower(log) as follower:
        follower.poll()
        writer.write("a\nb\n")
        events = poll_until(follower, lambda got: len(got) >= 2)
        shutil.copyfile(log, copy)
        with open(log, "r+b") as handle:
            handle.truncate(0)
        poll_until(follower, lambda got: len(got) >= 3, events)
        writer.write("c\n")
        poll_until(follower, lambda got: len(got) >= 4, events)
    path = str(log)
    assert events == [Line(path, "a"), Line(path, "b"), Truncated(path), Line(path, "c")]
    assert copy.read_bytes() == b"a\nb\n"
    assert log.read_bytes() == b"c\n"  # append mode wrote at the new end


def test_truncation_flushes_a_pending_fragment_first(
    tmp_path: Path, writer_for: Callable[[Path], Writer]
) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"")
    writer = writer_for(log)
    with Follower(log) as follower:
        follower.poll()
        writer.write("cut mid")
        follower.poll()
        with open(log, "r+b") as handle:
            handle.truncate(0)
        events = poll_until(follower, lambda got: len(got) >= 2)
    assert events == [Line(str(log), "cut mid", complete=False), Truncated(str(log))]


def test_deleted_then_recreated_file_is_picked_up_from_its_start(
    tmp_path: Path, writer_for: Callable[[Path], Writer]
) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"")
    writer = writer_for(log)
    with Follower(log) as follower:
        follower.poll()
        writer.write("last words\n")
        writer.send("close")
        os.remove(log)  # succeeds on Windows too: the follower shares delete access
        events = poll_until(follower, lambda got: len(got) >= 2)
        assert follower.poll() == []
        writer.write("again\n")
        poll_until(follower, lambda got: len(got) >= 4, events)
    path = str(log)
    assert events == [Line(path, "last words"), Missing(path), Appeared(path), Line(path, "again")]


def test_descriptor_mode_keeps_reading_the_renamed_file(
    tmp_path: Path, writer_for: Callable[[Path], Writer]
) -> None:
    log, old = tmp_path / "app.log", tmp_path / "app.log.1"
    log.write_bytes(b"")
    with Follower(log, by="descriptor") as follower:
        follower.poll()
        log.rename(old)
        log.write_bytes(b"ignored\n")
        writer_for(old).write("still here\n")
        events = poll_until(follower, lambda got: bool(got))
        assert [follower.poll() for _ in range(3)] == [[]] * 3
    assert events == [Line(str(log), "still here")]


def test_without_retry_a_deleted_file_is_dropped(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"x\n")
    with Follower(log, retry=False, from_start=True) as follower:
        assert texts(follower.poll()) == ["x"]
        os.remove(log)
        assert follower.poll() == [Missing(str(log))]
        assert follower.done
        log.write_bytes(b"back\n")
        assert follower.poll() == []


def test_rotations_under_a_free_running_writer_keep_every_line(
    tmp_path: Path, writer_for: Callable[[Path], Writer]
) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"")
    writer = writer_for(log)
    expected: list[str] = []
    events: list[Event] = []
    with Follower(log) as follower:
        follower.poll()
        for generation in range(5):
            start = generation * 400
            writer.send("burst", wait=False, prefix="g", start=start, count=400, pause=0)
            expected += [f"g{number}" for number in range(start, start + 400)]
            last = [expected[-1]]
            got = poll_until(follower, lambda got, last=last: texts(got)[-1:] == last, [])
            events += got
            writer.ack()
            writer.send("close")
            log.rename(tmp_path / f"app.log.{generation}")
            log.write_bytes(b"")  # logrotate "create": the new file exists at once
    assert texts(events) == expected
    assert sum(isinstance(event, Rotated) for event in events) == 4
