"""Build the real wheel, install it into a throwaway venv and drive the real script."""

from __future__ import annotations

import importlib.util
import os
import queue
import subprocess
import sys
import threading
import venv
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from conftest import GUARD, Writer

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def installed(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Yield the path of the installed ``followtail`` console script."""
    if importlib.util.find_spec("ensurepip") is None:
        pytest.skip("this Python cannot create a venv with pip (no ensurepip)")
    work = tmp_path_factory.mktemp("e2e")
    wheels = work / "wheels"
    # Reuse a locally installed build backend when there is one, so the test also
    # works offline; otherwise pip fetches hatchling into an isolated environment.
    isolation = ["--no-build-isolation"] if importlib.util.find_spec("hatchling") else []
    command = [sys.executable, "-m", "pip", "wheel", "--no-deps", "-q", *isolation]
    subprocess.run([*command, "-w", str(wheels), str(ROOT)], check=True)
    (wheel,) = wheels.glob("followtail-*.whl")
    env_dir = work / "venv"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    bin_dir = env_dir / ("Scripts" if os.name == "nt" else "bin")
    python = bin_dir / ("python.exe" if os.name == "nt" else "python")
    subprocess.run([str(python), "-m", "pip", "install", "-q", str(wheel)], check=True)
    yield bin_dir / ("followtail.exe" if os.name == "nt" else "followtail")


def _cli(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(script), *args], capture_output=True, text=True, timeout=120, check=False
    )


def test_the_installed_script_reports_the_version(installed: Path) -> None:
    from followtail import __version__

    result = _cli(installed, "--version")
    assert (result.returncode, result.stdout.strip()) == (0, f"followtail {__version__}")


def test_the_installed_script_prints_the_last_lines(installed: Path, tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_bytes(b"one\ntwo\nthree\n")
    result = _cli(installed, "-n", "2", str(log))
    assert (result.returncode, result.stdout, result.stderr) == (0, "two\nthree\n", "")


def test_the_installed_script_follows_a_live_writer(
    installed: Path, tmp_path: Path, writer_for: Callable[[Path], Writer]
) -> None:
    log = tmp_path / "app.log"
    log.write_bytes(b"history\n")
    tail = subprocess.Popen(
        [str(installed), "-F", "-n", "1", "-s", "0.02", str(log)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    lines: queue.Queue[str] = queue.Queue()

    def pump() -> None:
        assert tail.stdout is not None
        for line in tail.stdout:
            lines.put(line)

    threading.Thread(target=pump, daemon=True).start()
    try:
        assert lines.get(timeout=GUARD) == "history\n"
        writer = writer_for(log)
        writer.send("burst", prefix="live ", start=0, count=50, pause=0.001)
        assert [lines.get(timeout=GUARD) for _ in range(50)] == [f"live {n}\n" for n in range(50)]
        with open(log, "r+b") as handle:
            handle.truncate(0)
        writer.write("after truncation\n")
        assert lines.get(timeout=GUARD) == "after truncation\n"
    finally:
        tail.kill()
        tail.communicate()


def test_the_installed_library_imports_in_the_venv(installed: Path, tmp_path: Path) -> None:
    python = installed.parent / installed.name.replace("followtail", "python")
    log = tmp_path / "a.log"
    log.write_bytes(b"x\ny\n")
    code = (
        "import sys, followtail\n"
        "events = followtail.follow_events(sys.argv[1], from_start=True, max_idle=1, poll=0)\n"
        "print([event.text for event in events])\n"
    )
    result = subprocess.run(
        [str(python), "-c", code, str(log)], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "['x', 'y']"
