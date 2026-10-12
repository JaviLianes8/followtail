"""follow_events and follow: stop signals, timeouts, idle limits, injected time."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from followtail import Line, Missing, follow, follow_events


class FakeTime:
    """A clock and a sleep that advance together, recording every wait."""

    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds


def test_timeout_ends_the_iterator_after_a_final_poll(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"")
    fake = FakeTime()
    events = list(follow_events(log, poll=0.4, timeout=1.0, sleep=fake.sleep, clock=fake.clock))
    assert events == []
    assert fake.waits == [0.4, 0.4, pytest.approx(0.2)]  # never sleeps past the deadline


def test_a_threading_event_stops_it_and_is_used_to_wait(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"")
    stop = threading.Event()
    timer = threading.Timer(0.05, stop.set)
    timer.start()
    try:
        # poll=60 would hang the test if the wait did not wake up on the event.
        assert list(follow(log, poll=60, stop=stop)) == []
    finally:
        timer.cancel()


def test_a_callable_stop_is_checked_after_each_poll(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"")
    calls: list[int] = []

    def stop() -> bool:
        calls.append(1)
        return len(calls) >= 3

    fake = FakeTime()
    assert list(follow(log, poll=1, stop=stop, sleep=fake.sleep)) == []
    assert len(fake.waits) == 2


def test_lines_written_before_the_stop_are_still_delivered(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"")
    stop = threading.Event()

    def sleep(_: float) -> None:
        with open(log, "ab") as handle:
            handle.write(b"last\n")
        stop.set()

    assert list(follow(log, poll=1, stop=stop, sleep=sleep)) == ["last"]


def test_max_idle_counts_consecutive_idle_polls(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"")
    fake = FakeTime()
    assert list(follow(log, poll=0.1, max_idle=4, sleep=fake.sleep)) == []
    assert fake.waits == [0.1, 0.1, 0.1]


def test_partial_flush_emits_the_fragment_at_the_end(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"tail without newline")
    events = list(follow_events(log, from_start=True, partial="flush", max_idle=1, poll=0))
    assert events == [Line(str(log), "tail without newline", complete=False)]


def test_wait_policy_never_emits_an_unterminated_fragment(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"done\nhalf")
    lines = list(follow(log, from_start=True, max_idle=5, poll=0, sleep=lambda _: None))
    assert lines == ["done"]


def test_retry_false_ends_when_no_file_is_left(tmp_path: Path) -> None:
    log = tmp_path / "missing.log"
    assert list(follow_events(log, retry=False)) == [Missing(str(log))]
    assert list(follow(log, retry=False)) == []


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"poll": -1}, ValueError),
        ({"poll": float("nan")}, ValueError),
        ({"poll": "1"}, TypeError),
        ({"timeout": -0.5}, ValueError),
        ({"max_idle": -1}, ValueError),
        ({"stop": 42}, TypeError),
    ],
)
def test_bad_pacing_arguments_raise_at_call_time(
    tmp_path: Path, kwargs: dict[str, object], error: type[Exception]
) -> None:
    with pytest.raises(error):
        follow(tmp_path / "a.log", **kwargs)  # type: ignore[arg-type]


def test_closing_the_generator_releases_the_file(tmp_path: Path) -> None:
    folder = tmp_path / "logs"
    folder.mkdir()
    log = folder / "a.log"
    log.write_bytes(b"one\ntwo\n")
    lines = follow(log, from_start=True)
    assert next(lines) == "one"
    lines.close()
    # Windows refuses to rename a folder while any file in it is open.
    folder.rename(tmp_path / "moved")
