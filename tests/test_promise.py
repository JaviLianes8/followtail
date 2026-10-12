"""The whole promise, end to end, through the public blocking iterator.

A real writer process appends while a consumer thread runs ``follow_events`` with real
sleeps. The test drives every situation a followed log meets (start position, appends,
a line written in two parts, an atomic create rotation, a copytruncate rotation, a
deletion and recreation, a free running burst) and then checks the complete event
stream: every line exactly once, in order, each change reported exactly once.
"""

from __future__ import annotations

import os
import queue
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path

from conftest import GUARD, Writer

from followtail import Appeared, Event, Line, Missing, Rotated, Truncated, follow_events


class Consumer:
    """Run follow_events in a thread and hand its events over one by one."""

    def __init__(self, log: Path) -> None:
        self.stop = threading.Event()
        self.events: queue.Queue[Event] = queue.Queue()
        self.seen: list[Event] = []
        self.error: BaseException | None = None
        # The consumer holds the gate except while it sleeps, so a test holding it
        # knows no poll can run in the middle of a multi step change.
        self.gate = threading.Lock()
        self._stream = follow_events(log, lines=2, poll=0.01, stop=self.stop, sleep=self._nap)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _nap(self, seconds: float) -> None:
        self.gate.release()
        try:
            time.sleep(seconds)
        finally:
            self.gate.acquire()

    def _run(self) -> None:
        self.gate.acquire()
        try:
            for event in self._stream:
                self.events.put(event)
        except BaseException as error:  # pragma: no cover - reported by finish()
            self.error = error
        finally:
            self.gate.release()

    def expect(self, *wanted: Event) -> None:
        for _ in wanted:
            self.seen.append(self.events.get(timeout=GUARD))
        assert self.seen[-len(wanted) :] == list(wanted)

    def finish(self) -> list[Event]:
        self.stop.set()
        self._thread.join(GUARD)
        assert not self._thread.is_alive() and self.error is None
        while not self.events.empty():
            self.seen.append(self.events.get())
        return self.seen


def test_every_line_once_in_order_across_every_kind_of_change(
    tmp_path: Path, writer_for: Callable[[Path], Writer]
) -> None:
    log = tmp_path / "app.log"
    path = str(log)
    log.write_bytes(b"skipped\nkept 1\nkept 2\n")
    consumer = Consumer(log)
    consumer.expect(Line(path, "kept 1"), Line(path, "kept 2"))

    writer = writer_for(log)
    writer.write("appended\n")
    consumer.expect(Line(path, "appended"))

    writer.write("written in ")
    writer.write("two parts\n")
    consumer.expect(Line(path, "written in two parts"))

    writer.write("before rotation\n")
    writer.send("close")
    with consumer.gate:  # logrotate "create": rename, then a new file under the name
        log.rename(tmp_path / "app.log.1")
        writer.write("after rotation\n")
    consumer.expect(Line(path, "before rotation"), Rotated(path), Line(path, "after rotation"))

    writer.write("before copytruncate\n")
    consumer.expect(Line(path, "before copytruncate"))
    shutil.copyfile(log, tmp_path / "app.log.2")
    with open(log, "r+b") as handle:
        handle.truncate(0)
    consumer.expect(Truncated(path))
    writer.write("after copytruncate\n")
    consumer.expect(Line(path, "after copytruncate"))

    writer.send("close")
    os.remove(log)
    consumer.expect(Missing(path))
    writer.write("recreated\n")
    consumer.expect(Appeared(path), Line(path, "recreated"))

    writer.send("burst", prefix="burst ", start=0, count=500, pause=0)
    consumer.expect(*(Line(path, f"burst {number}") for number in range(500)))

    assert consumer.finish() == [
        Line(path, "kept 1"),
        Line(path, "kept 2"),
        Line(path, "appended"),
        Line(path, "written in two parts"),
        Line(path, "before rotation"),
        Rotated(path),
        Line(path, "after rotation"),
        Line(path, "before copytruncate"),
        Truncated(path),
        Line(path, "after copytruncate"),
        Missing(path),
        Appeared(path),
        Line(path, "recreated"),
        *(Line(path, f"burst {number}") for number in range(500)),
    ]
