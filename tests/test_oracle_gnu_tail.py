"""Oracle: GNU ``tail -F`` and ``followtail -F`` must print the same thing.

The scenario in ``oracle_scenario.py`` (appends, a line written in two parts,
copytruncate, an atomic create rotation, deletion and recreation, a burst) and a
second one with several operands (headers, an empty file, a file missing at start, a
directory, ``-n +N`` with lines appended later) run under
GNU coreutils ``tail`` in polling mode and in inotify mode, and under followtail, all
following the same file on a Linux filesystem. On Windows it runs inside WSL. GNU
``tail`` is looked up as ``gnutail`` (Ubuntu ships uutils as ``tail``) or as a ``tail``
whose ``--version`` names GNU coreutils.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
TIMEOUT = 300


def _linux(*argv: str) -> list[str]:
    return ["wsl", "-e", *argv] if sys.platform == "win32" else list(argv)


def _gnu_tail() -> str:
    if sys.platform == "win32" and shutil.which("wsl") is None:
        pytest.skip("WSL is not available")
    for candidate in ("gnutail", "tail"):
        try:
            probe = subprocess.run(
                _linux(candidate, "--version"), capture_output=True, text=True, timeout=60
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0 and "GNU coreutils" in probe.stdout:
            return candidate
    pytest.skip("GNU coreutils tail is not installed")


def _linux_path(path: Path) -> str:
    if sys.platform != "win32":
        return str(path)
    converted = subprocess.run(
        ["wsl", "-e", "wslpath", "-a", path.as_posix()],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return converted.stdout.strip()


@pytest.fixture(scope="module")
def outputs() -> dict[str, str]:
    tail = _gnu_tail()
    python = "python3" if sys.platform == "win32" else sys.executable
    script, src = _linux_path(HERE / "oracle_scenario.py"), _linux_path(HERE.parent / "src")
    run = subprocess.run(
        _linux(python, script, src, tail), capture_output=True, text=True, timeout=TIMEOUT
    )
    assert run.returncode == 0, run.stderr
    result: dict[str, str] = json.loads(run.stdout)
    result["tail"] = tail
    return result


def test_the_printed_lines_match_gnu_tail_in_polling_mode(outputs: dict[str, str]) -> None:
    assert outputs["followtail_out"] == outputs["gnu_poll_out"]
    assert outputs["followtail_out"].count("\n") == 207


def test_the_printed_lines_match_gnu_tail_with_inotify(outputs: dict[str, str]) -> None:
    assert outputs["followtail_out"] == outputs["gnu_inotify_out"]


def test_the_notices_match_gnu_tail_word_for_word(outputs: dict[str, str]) -> None:
    ours = outputs["followtail_err"].replace("followtail: ", "PROG: ")
    for mode in ("gnu_poll_err", "gnu_inotify_err"):
        assert ours == outputs[mode].replace(f"{outputs['tail']}: ", "PROG: ")
    assert [line.split("' ")[-1] for line in ours.splitlines()[1:]] == [
        "has been replaced;  following new file",
        "has become inaccessible: No such file or directory",
        "has appeared;  following new file",
    ]


def test_several_files_match_gnu_tail_headers_and_notices(outputs: dict[str, str]) -> None:
    ours = outputs["several_followtail_err"].replace("followtail: ", "PROG: ")
    for mode in ("gnu_poll", "gnu_inotify"):
        assert outputs["several_followtail_out"] == outputs[f"several_{mode}_out"]
        assert ours == outputs[f"several_{mode}_err"].replace(f"{outputs['tail']}: ", "PROG: ")
    assert "==> dd <==" in outputs["several_followtail_out"]
