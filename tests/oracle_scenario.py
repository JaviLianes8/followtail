"""Run writer scenarios under GNU ``tail -F`` and ``followtail -F`` side by side.

Usage: ``python3 oracle_scenario.py SRC_DIR TAIL_BINARY``. Runs on Linux (the Windows
test starts it inside WSL so the followed files live on a Linux filesystem). Prints a
JSON object with each follower's stdout and stderr per scenario. Each step waits until
every follower has caught up before the next one starts, so the comparison never
depends on timing; the waits are guards and fail after a generous limit.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

GUARD = 30.0
HERE = Path(__file__).resolve().parent


class Run:
    """GNU tail (polling and inotify) and followtail following the same operands."""

    def __init__(self, work: Path, src: str, tail: str, options: list[str], files: list[str]):
        self.work = work
        common = ["-F", *options, "-s", "0.05", *files]
        self.argv = {
            "gnu_poll": [tail, "---disable-inotify", *common],
            "gnu_inotify": [tail, *common],
            "followtail": [sys.executable, "-m", "followtail", *common],
        }
        env = {**os.environ, "PYTHONPATH": src}
        self.files = {}
        self.procs = {}
        for name, argv in self.argv.items():
            out = open(work / f"{name}.out", "wb")  # noqa: SIM115
            err = open(work / f"{name}.err", "wb")  # noqa: SIM115
            self.files[name] = (out, err)
            self.procs[name] = subprocess.Popen(argv, stdout=out, stderr=err, env=env, cwd=work)

    def wait(self, ready: Callable[[bytes, str], bool]) -> None:
        """Wait until ``ready(stdout, stderr)`` holds for every follower."""
        limit = time.monotonic() + GUARD
        for name in self.argv:
            while True:
                out = (self.work / f"{name}.out").read_bytes()
                err = (self.work / f"{name}.err").read_text()
                if ready(out, err):
                    break
                if time.monotonic() > limit:
                    raise SystemExit(f"{name} never caught up: {out!r} {err!r}")
                time.sleep(0.01)

    def finish(self, prefix: str) -> dict[str, str]:
        for proc in self.procs.values():
            proc.terminate()
            proc.wait(GUARD)
        result = {}
        for name, (out, err) in self.files.items():
            out.close()
            err.close()
            result[f"{prefix}{name}_out"] = (self.work / f"{name}.out").read_text()
            result[f"{prefix}{name}_err"] = (self.work / f"{name}.err").read_text()
        return result


def lines(count: int, notice: str = "") -> Callable[[bytes, str], bool]:
    return lambda out, err: out.count(b"\n") >= count and notice in err


def rotation(work: Path, src: str, tail: str) -> dict[str, str]:
    """One file through appends, a split line and every rotation style."""
    log = work / "app.log"
    log.write_bytes(b"first\nsecond\n")
    run = Run(work, src, tail, ["-n", "1"], [str(log)])
    writer = subprocess.Popen(
        [sys.executable, "-u", str(HERE / "writer_proc.py"), str(log)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )

    def send(op: str, **fields: object) -> None:
        assert writer.stdin is not None and writer.stdout is not None
        writer.stdin.write(json.dumps({"op": op, **fields}) + "\n")
        writer.stdin.flush()
        assert writer.stdout.readline().strip() == "ok"

    try:
        run.wait(lines(1))
        send("write", text="appended 1\nappended 2\n")
        run.wait(lines(3))
        send("write", text="written in ")
        run.wait(lambda out, err: out.endswith(b"written in "))  # shown before its end
        send("write", text="two parts\n")
        run.wait(lines(4))
        shutil.copyfile(log, work / "app.log.1")  # logrotate copytruncate
        with open(log, "r+b") as handle:
            handle.truncate(0)
        run.wait(lines(4, "file truncated"))
        send("write", text="after copytruncate\n")
        run.wait(lines(5))
        send("close")
        fresh = work / "app.log.new"
        fresh.write_bytes(b"after create rotation\n")
        os.link(log, work / "app.log.2")
        os.replace(fresh, log)  # the name moves to a new file in one step
        run.wait(lines(6))
        os.remove(log)
        run.wait(lines(6, "inaccessible"))
        send("write", text="recreated\n")
        run.wait(lines(7, "appeared"))
        send("burst", prefix="burst ", start=0, count=200, pause=0)
        run.wait(lines(207))
    finally:
        assert writer.stdin is not None and writer.stdout is not None
        writer.stdin.close()  # end of input: the writer closes its file and exits
        writer.wait(GUARD)
        writer.stdout.close()
    return run.finish("")


def several(work: Path, src: str, tail: str) -> dict[str, str]:
    """Headers, a file missing at start, an empty file, a directory and ``-n +N``."""
    (work / "a").write_bytes(b"a1\na2\na3\n")
    (work / "b").write_bytes(b"")
    (work / "dd").mkdir()
    run = Run(work, src, tail, ["-n", "+2"], ["a", "b", "c", "dd"])
    run.wait(lambda out, err: b"==> dd <==" in out and "cannot follow" in err)
    (work / "c").write_bytes(b"c1\n")
    run.wait(lambda out, err: out.endswith(b"c1\n") and "appeared" in err)
    with open(work / "b", "ab") as handle:
        handle.write(b"b1\n")
    run.wait(lambda out, err: out.endswith(b"b1\n"))
    with open(work / "a", "ab") as handle:
        handle.write(b"a4\n")
    run.wait(lambda out, err: out.endswith(b"a4\n"))
    return run.finish("several_")


def main(src: str, tail: str) -> None:
    result: dict[str, str] = {}
    for scenario in (rotation, several):
        work = Path(tempfile.mkdtemp(prefix="followtail-oracle-"))
        try:
            result.update(scenario(work, src, tail))
        finally:
            shutil.rmtree(work)
    print(json.dumps(result))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
