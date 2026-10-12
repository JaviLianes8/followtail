"""What a writer may do to a file while it is followed, per platform."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from followtail import Follower, Line, Rotated

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing rules")
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX rename semantics")


def test_a_followed_file_can_be_renamed_truncated_and_deleted(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"x\n")
    with Follower(log) as follower:
        follower.poll()  # holds the descriptor from here on
        log.rename(tmp_path / "app.log.1")
        log.write_bytes(b"y\n")
        with open(log, "r+b") as handle:
            handle.truncate(0)
        os.remove(tmp_path / "app.log.1")
        os.remove(log)


@windows_only
def test_a_plain_open_reader_would_block_rotation_on_windows(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"x\n")
    with open(log, "rb"), pytest.raises(PermissionError):
        log.rename(tmp_path / "app.log.1")  # why followtail opens with FILE_SHARE_DELETE


@windows_only
def test_replacing_the_followed_name_in_one_step_fails_on_windows(tmp_path: Path) -> None:
    log, fresh = tmp_path / "app.log", tmp_path / "app.log.new"
    log.write_bytes(b"x\n")
    fresh.write_bytes(b"y\n")
    with Follower(log) as follower:
        follower.poll()
        # Documented limit: MoveFileEx cannot replace a file that is open, whatever the
        # share mode. Rotate by renaming the old file away, then creating the new one.
        with pytest.raises(PermissionError):
            os.replace(fresh, log)


@posix_only
def test_an_atomic_replace_of_the_name_is_a_rotation(tmp_path: Path) -> None:
    log, fresh = tmp_path / "app.log", tmp_path / "app.log.new"
    log.write_bytes(b"")
    with Follower(log) as follower:
        follower.poll()
        with open(log, "ab") as handle:
            handle.write(b"old tail\n")
        fresh.write_bytes(b"new head\n")
        os.replace(fresh, log)
        events = follower.poll()
    path = str(log)
    assert events == [Line(path, "old tail"), Rotated(path), Line(path, "new head")]
