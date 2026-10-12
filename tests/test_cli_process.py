"""The command line tool as a real process: live following, closed pipes, Ctrl+C."""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import GUARD, Writer

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _spawn(*args: str) -> subprocess.Popen[str]:
    env = {**os.environ, "PYTHONPATH": SRC, "PYTHONIOENCODING": "utf-8"}
    return subprocess.Popen(
        [sys.executable, "-m", "followtail", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def _reader(stream: object) -> queue.Queue[str]:
    lines: queue.Queue[str] = queue.Queue()

    def pump() -> None:
        for line in stream:  # type: ignore[attr-defined]
            lines.put(line)

    threading.Thread(target=pump, daemon=True).start()
    return lines


def test_the_process_follows_a_live_writer_across_rotation(
    tmp_path: Path, writer_for: Callable[[Path], Writer]
) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"one\ntwo\n")
    tail = _spawn("-F", "-n", "1", "-s", "0.02", str(log))
    try:
        out, err = _reader(tail.stdout), _reader(tail.stderr)
        assert out.get(timeout=GUARD) == "two\n"
        writer = writer_for(log)
        writer.write("three\n")
        assert out.get(timeout=GUARD) == "three\n"
        writer.send("close")
        log.rename(tmp_path / "app.log.1")
        writer.write("four\n")
        assert out.get(timeout=GUARD) == "four\n"
        assert (
            err.get(timeout=GUARD)
            == f"followtail: '{log}' has been replaced;  following new file\n"
        )
    finally:
        tail.kill()
        tail.communicate()


def test_a_closed_pipe_ends_the_process_quietly(tmp_path: Path) -> None:
    log = tmp_path / "big.log"
    log.write_bytes(b"".join(b"line %d\n" % n for n in range(300_000)))
    tail = _spawn("-n", "+1", str(log))
    assert tail.stdout is not None and tail.stderr is not None
    assert tail.stdout.readline() == "line 0\n"
    tail.stdout.close()  # the reader goes away, like `| head -1`
    status = tail.wait(timeout=GUARD)
    err = tail.stderr.read()
    tail.stderr.close()
    assert "Traceback" not in err and err == ""
    assert status == 0


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT delivery needs a POSIX process")
def test_ctrl_c_ends_a_follow_with_status_130_and_no_traceback(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"ready\n")
    tail = _spawn("-F", "-n", "1", "-s", "0.02", str(log))
    assert tail.stdout is not None
    assert tail.stdout.readline() == "ready\n"
    tail.send_signal(signal.SIGINT)
    _, err = tail.communicate(timeout=GUARD)
    assert tail.returncode == 130 and err == ""
