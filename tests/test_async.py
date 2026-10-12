"""afollow and afollow_events: the same behaviour with awaitable waits."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from followtail import Appeared, Line, Missing, afollow, afollow_events


async def _collect_lines(log: Path, **kwargs: object) -> list[str]:
    return [line async for line in afollow(log, **kwargs)]  # type: ignore[arg-type]


def test_afollow_yields_lines_and_awaits_the_injected_sleep(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"old\n")
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 1:
            with open(log, "ab") as handle:
                handle.write(b"new\n")

    lines = asyncio.run(_collect_lines(log, poll=0.25, max_idle=2, sleep=sleep))
    assert lines == ["new"]
    assert waits == [0.25, 0.25]


def test_afollow_events_reports_missing_and_appeared(tmp_path: Path) -> None:
    log = tmp_path / "late.log"

    async def sleep(_: float) -> None:
        log.write_bytes(b"hello\n")

    async def run() -> list[object]:
        return [event async for event in afollow_events(log, max_idle=2, sleep=sleep)]

    path = str(log)
    assert asyncio.run(run()) == [Missing(path), Appeared(path), Line(path, "hello")]


def test_an_asyncio_event_wakes_the_wait_at_once(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"")

    async def run() -> list[str]:
        stop = asyncio.Event()
        asyncio.get_running_loop().call_later(0.05, stop.set)
        # poll=60 would hang the test if setting the event did not end the wait.
        return await asyncio.wait_for(_collect_lines(log, poll=60, stop=stop), 30)

    assert asyncio.run(run()) == []


def test_other_tasks_keep_running_while_following(tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"")

    async def writer() -> None:
        for number in range(3):
            await asyncio.sleep(0.01)
            with open(log, "ab") as handle:
                handle.write(b"line %d\n" % number)

    async def run() -> list[str]:
        lines: list[str] = []
        task = asyncio.create_task(writer())
        async for line in afollow(log, poll=0.005):
            lines.append(line)
            if len(lines) == 3:
                break
        await task
        return lines

    assert asyncio.run(asyncio.wait_for(run(), 30)) == ["line 0", "line 1", "line 2"]


def test_async_arguments_are_validated_at_call_time(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        afollow(tmp_path / "a.log", poll=-1)
    with pytest.raises(ValueError):
        afollow_events(tmp_path / "a.log", by="inode")  # type: ignore[arg-type]
