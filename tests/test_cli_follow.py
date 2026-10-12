"""The command line tool in follow mode, in process, with injected time."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from followtail import _clirun
from followtail._cli import main

Step = Callable[[], None]


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., None]]:
    """Replace the CLI's clock and sleep; each idle wait runs the next scripted step."""
    now = [0.0]
    steps: list[Step] = []

    def sleep(seconds: float) -> None:
        now[0] += seconds
        if steps:
            steps.pop(0)()

    monkeypatch.setattr(_clirun, "_clock", lambda: now[0])
    monkeypatch.setattr(_clirun, "_sleep", sleep)
    yield lambda *more: steps.extend(more)


def _append(path: Path, data: bytes) -> Step:
    def step() -> None:
        with open(path, "ab") as handle:
            handle.write(data)

    return step


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    status = main(["-s", "1", "--timeout", "20", *argv])
    out, err = capsys.readouterr()
    return status, out, err


def test_new_lines_and_a_truncation_notice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], script: Callable[..., None]
) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"old\n")
    script(_append(log, b"new\n"), lambda: log.write_bytes(b"short\n"))
    status, out, err = _run(capsys, "-F", "-n", "1", str(log))
    assert (status, out) == (0, "old\nnew\nshort\n")
    assert err == f"followtail: {log}: file truncated\n"


def test_a_line_being_written_is_shown_like_gnu_tail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], script: Callable[..., None]
) -> None:
    log = tmp_path / "a.log"
    shown: list[str] = []

    def finish() -> None:
        shown.append(capsys.readouterr().out)  # what was on screen before the newline
        _append(log, b" done\n")()

    for policy, before in (("flush", "half"), ("wait", "")):
        log.write_bytes(b"")
        script(_append(log, b"half"), lambda: None, finish)
        status, out, _ = _run(capsys, "-F", "--partial", policy, str(log))
        assert (status, shown.pop() + out) == (0, "half done\n")
        assert out == ("half done\n" if not before else " done\n")


def test_plus_n_skips_lines_of_the_first_file_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], script: Callable[..., None]
) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"1\n2\n3\n")
    script(lambda: log.write_bytes(b"x\n"))  # truncation: a new file, nothing skipped
    status, out, _ = _run(capsys, "-F", "-n", "+3", str(log))
    assert (status, out) == (0, "3\nx\n")


def test_headers_for_every_file_even_empty_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], script: Callable[..., None]
) -> None:
    first, second = tmp_path / "e1", tmp_path / "e2"
    first.write_bytes(b"")
    second.write_bytes(b"")
    script(_append(first, b"late\n"))
    out = _run(capsys, "-F", str(first), str(second))[1]
    assert out == f"==> {first} <==\n\n==> {second} <==\n\n==> {first} <==\nlate\n"


def test_a_directory_is_reported_and_the_other_files_still_followed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], script: Callable[..., None]
) -> None:
    log, folder = tmp_path / "x.log", tmp_path / "dd"
    log.write_bytes(b"x\n")
    folder.mkdir()
    script(_append(log, b"y\n"))
    status, out, err = _run(capsys, "-F", "-q", str(log), str(folder))
    assert (status, out) == (1, "x\ny\n")
    assert err.splitlines() == [
        f"followtail: error reading '{folder}': Is a directory",
        f"followtail: {folder}: cannot follow end of this type of file",
    ]


def test_only_directories_leaves_no_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, err = _run(capsys, "-F", "-q", str(tmp_path))
    assert (status, out) == (1, "")
    assert err.splitlines()[-1] == "followtail: no files remaining"


def test_without_retry_a_missing_file_leaves_no_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope.log"
    status, out, err = _run(capsys, "-f", str(missing))
    assert (status, out) == (1, "")
    assert err.splitlines() == [
        f"followtail: cannot open '{missing}' for reading: No such file or directory",
        "followtail: no files remaining",
    ]


def test_follow_takes_an_attached_value_or_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], script: Callable[..., None]
) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"a\n")
    assert _run(capsys, "--follow", str(log)) == (0, "a\n", "")
    assert _run(capsys, "--follow=name", "--retry", str(log)) == (0, "a\n", "")
    with pytest.raises(SystemExit) as exit_:
        main(["--follow=inode", str(log)])
    assert exit_.value.code == 1


def test_ctrl_c_exits_130_quietly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(_: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(_clirun, "_sleep", interrupted)
    log = tmp_path / "a.log"
    log.write_bytes(b"seen\n")
    assert main(["-F", str(log)]) == 130
    assert capsys.readouterr() == ("seen\n", "")


def test_plus_n_never_skips_lines_appended_later(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], script: Callable[..., None]
) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"")
    script(_append(log, b"new 1\nnew 2\n"))
    assert _run(capsys, "-F", "-n", "+3", str(log))[1] == "new 1\nnew 2\n"
