"""Shared helpers: a real writer subprocess and bounded waits on a Follower."""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from followtail import Event, Follower, Line

WRITER = Path(__file__).with_name("writer_proc.py")
# Waits below are guards against a hang, never the thing being measured: every test
# proceeds as soon as its condition holds, and only fails if it never does.
GUARD = 30.0


class Writer:
    """A separate Python process appending to one file on command."""

    def __init__(self, path: Path) -> None:
        self._process = subprocess.Popen(
            [sys.executable, "-u", str(WRITER), str(path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        self._acks: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._acks.put(line.strip())

    def send(self, op: str, wait: bool = True, **fields: object) -> None:
        """Send one command; with ``wait`` block until the writer has flushed it."""
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps({"op": op, **fields}) + "\n")
        self._process.stdin.flush()
        if wait:
            self.ack()

    def ack(self) -> None:
        """Wait for the next acknowledgement."""
        assert self._acks.get(timeout=GUARD) == "ok"

    def write(self, text: str) -> None:
        self.send("write", text=text)

    def stop(self) -> None:
        if self._process.poll() is None:
            try:
                self.send("exit", wait=False)
                self._process.wait(timeout=GUARD)
            except (OSError, subprocess.TimeoutExpired):
                self._process.kill()
                self._process.wait()
        for stream in (self._process.stdin, self._process.stdout):
            if stream is not None:
                stream.close()


@pytest.fixture
def writer_for() -> Iterator[Callable[[Path], Writer]]:
    """Start writer processes for paths; every one is stopped at teardown."""
    started: list[Writer] = []

    def start(path: Path) -> Writer:
        writer = Writer(path)
        started.append(writer)
        return writer

    yield start
    for writer in started:
        writer.stop()


def poll_until(
    follower: Follower, done: Callable[[list[Event]], bool], into: list[Event] | None = None
) -> list[Event]:
    """Poll until ``done(events)`` holds; fail after ``GUARD`` seconds."""
    events = [] if into is None else into
    limit = time.monotonic() + GUARD
    while not done(events):
        assert time.monotonic() < limit, f"condition never held; events so far: {events}"
        events.extend(follower.poll())
        if not follower.moved:
            time.sleep(0.005)
    return events


def texts(events: list[Event]) -> list[str]:
    """The text of every line event, in order."""
    return [event.text for event in events if isinstance(event, Line)]
