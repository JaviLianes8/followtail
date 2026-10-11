from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

from followtail import follow


def _no_sleep(_: float) -> None:
    return None


def _scripted(steps: list[Callable[[], None]]) -> Callable[[float], None]:
    """A sleep stand-in that runs one scripted file mutation per idle poll."""
    pending: Iterator[Callable[[], None]] = iter(steps)

    def sleep(_: float) -> None:
        step = next(pending, None)
        if step is not None:
            step()

    return sleep


def _append(path: Path, text: str) -> Callable[[], None]:
    def step() -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)

    return step


def test_from_start_replays_existing_lines(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_text("one\ntwo\n", encoding="utf-8")

    lines = list(follow(log, poll=0, from_start=True, max_idle=1, sleep=_no_sleep))

    assert lines == ["one", "two"]


def test_default_starts_at_end_and_yields_appended_lines(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_text("existing\n", encoding="utf-8")
    sleep = _scripted([_append(log, "fresh1\nfresh2\n")])

    lines = list(follow(log, poll=0, max_idle=3, sleep=sleep))

    assert lines == ["fresh1", "fresh2"]


def test_partial_line_is_buffered_until_newline_arrives(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_text("", encoding="utf-8")
    sleep = _scripted([_append(log, "half"), _append(log, "-done\n")])

    lines = list(follow(log, poll=0, from_start=True, max_idle=4, sleep=sleep))

    assert lines == ["half-done"]


def test_rotation_by_truncate_reads_the_new_content(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_text("old-a\nold-b\n", encoding="utf-8")

    def truncate_and_write() -> None:
        log.write_text("after\n", encoding="utf-8")

    sleep = _scripted([truncate_and_write])
    lines = list(follow(log, poll=0, max_idle=3, sleep=sleep))

    assert lines == ["after"]


def test_rotation_by_rename_and_recreate_follows_the_new_file(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_text("before\n", encoding="utf-8")

    def rotate() -> None:
        log.rename(tmp_path / "app.log.1")
        log.write_text("reborn\n", encoding="utf-8")

    sleep = _scripted([rotate])
    lines = list(follow(log, poll=0, max_idle=3, sleep=sleep))

    assert lines == ["reborn"]


def test_missing_file_is_tolerated_until_it_appears(tmp_path: Path) -> None:
    log = tmp_path / "late.log"
    sleep = _scripted([_append(log, "arrived\n")])

    lines = list(follow(log, poll=0, from_start=True, max_idle=3, sleep=sleep))

    assert lines == ["arrived"]


def test_carriage_returns_are_stripped(tmp_path: Path) -> None:
    log = tmp_path / "crlf.log"
    log.write_bytes(b"line-a\r\nline-b\r\n")

    lines = list(follow(log, poll=0, from_start=True, max_idle=1, sleep=_no_sleep))

    assert lines == ["line-a", "line-b"]
