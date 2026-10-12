"""The followtail command line tool, run in process."""

from __future__ import annotations

from pathlib import Path

import pytest

from followtail import __version__
from followtail._cli import main


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    status = main(list(argv))
    out, err = capsys.readouterr()
    return status, out, err


def test_prints_the_last_lines_and_exits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"".join(b"%d\n" % n for n in range(1, 21)))
    assert _run(capsys, str(log)) == (0, "".join(f"{n}\n" for n in range(11, 21)), "")
    assert _run(capsys, "-n", "2", str(log)) == (0, "19\n20\n", "")
    assert _run(capsys, "-n", "-2", str(log)) == (0, "19\n20\n", "")
    assert _run(capsys, "-n", "0", str(log)) == (0, "", "")


def test_plus_n_starts_at_that_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"1\n2\n3\n")
    assert _run(capsys, "-n", "+2", str(log))[1] == "2\n3\n"
    assert _run(capsys, "-n", "+1", str(log))[1] == "1\n2\n3\n"
    assert _run(capsys, "-n", "+0", str(log))[1] == "1\n2\n3\n"


def test_an_unterminated_last_line_is_printed_without_a_newline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"a\r\nb")
    assert _run(capsys, str(log))[1] == "a\nb"


def test_several_files_get_headers(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    first, second = tmp_path / "a.log", tmp_path / "b.log"
    first.write_bytes(b"x\n")
    second.write_bytes(b"y\n")
    out = _run(capsys, "-n", "1", str(first), str(second))[1]
    assert out == f"==> {first} <==\nx\n\n==> {second} <==\ny\n"
    assert _run(capsys, "-q", str(first), str(second))[1] == "x\ny\n"
    assert _run(capsys, "-v", str(first))[1] == f"==> {first} <==\nx\n"


def test_a_missing_file_is_reported_and_the_rest_still_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log, missing = tmp_path / "a.log", tmp_path / "nope.log"
    log.write_bytes(b"ok\n")
    status, out, err = _run(capsys, "-q", str(missing), str(log))
    assert (status, out) == (1, "ok\n")
    assert err == f"followtail: cannot open '{missing}' for reading: No such file or directory\n"


def test_invalid_bytes_are_replaced_by_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"bad \xff\n")
    assert _run(capsys, str(log))[1] == "bad �\n"
    status, _, err = _run(capsys, "--errors", "strict", str(log))
    assert status == 1 and "can't decode" in err


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["-n", "ten", "a.log"],
        ["-s", "-1", "a.log"],
        ["--timeout", "inf", "a.log"],
        ["-f", "-F", "a.log"],
        ["--follow=inode", "a.log"],
        ["--encoding", "utf-16", "a.log"],
    ],
)
def test_bad_usage_exits_one_with_a_message_on_stderr(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    try:
        status, out, err = _run(capsys, *argv)
    except SystemExit as exit_:
        status, (out, err) = int(exit_.code or 0), capsys.readouterr()
    assert status == 1 and out == ""
    assert err.startswith(("usage:", "followtail:"))


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_:
        main(["--version"])
    assert exit_.value.code == 0
    assert capsys.readouterr().out.strip() == f"followtail {__version__}"


def test_follow_without_retry_gives_up_on_a_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope.log"
    status, out, err = _run(capsys, "-f", str(missing))
    assert (status, out) == (1, "")
    assert err.splitlines() == [
        f"followtail: cannot open '{missing}' for reading: No such file or directory",
        "followtail: no files remaining",
    ]


def test_a_directory_is_reported_like_gnu_tail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "dd"
    folder.mkdir()
    status, out, err = _run(capsys, "-v", str(folder))
    assert (status, out) == (1, f"==> {folder} <==\n")
    assert err == f"followtail: error reading '{folder}': Is a directory\n"


def test_an_unknown_error_handler_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"\xff\n")
    with pytest.raises(SystemExit) as exit_:
        main(["--errors", "bogus", str(log)])
    assert exit_.value.code == 1
    assert "unknown error handler" in capsys.readouterr().err
