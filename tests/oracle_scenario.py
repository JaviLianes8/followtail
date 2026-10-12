"""Run one writer scenario under GNU ``tail -F`` and ``followtail -F`` side by side.

Usage: ``python3 oracle_scenario.py SRC_DIR TAIL_BINARY``. Runs on Linux (the Windows
test starts it inside WSL so the followed file lives on a Linux filesystem). Prints a
JSON object with each follower's stdout and stderr. Each step waits until every
follower has caught up before the next one starts, so the comparison never depends on
timing; the waits are guards and fail after a generous limit.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

GUARD = 30.0
HERE = Path(__file__).resolve().parent


def main(src: str, tail: str) -> None:
    work = Path(tempfile.mkdtemp(prefix="followtail-oracle-"))
    log = work / "app.log"
    log.write_bytes(b"first\nsecond\n")
    env = {**os.environ, "PYTHONPATH": src}
    followers = {
        "gnu_poll": [tail, "---disable-inotify", "-F", "-n", "1", "-s", "0.05", str(log)],
        "gnu_inotify": [tail, "-F", "-n", "1", "-s", "0.05", str(log)],
        "followtail": [sys.executable, "-m", "followtail", "-F", "-n", "1", "-s", "0.05", str(log)],
    }
    procs, files = {}, {}
    for name, argv in followers.items():
        out, err = open(work / f"{name}.out", "wb"), open(work / f"{name}.err", "wb")  # noqa: SIM115
        files[name] = (out, err)
        procs[name] = subprocess.Popen(argv, stdout=out, stderr=err, env=env, cwd=work)
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

    def wait(lines: int, notice: str = "") -> None:
        limit = time.monotonic() + GUARD
        for name in followers:
            while True:
                out = (work / f"{name}.out").read_bytes()
                err = (work / f"{name}.err").read_text()
                if out.count(b"\n") >= lines and notice in err:
                    break
                if time.monotonic() > limit:
                    raise SystemExit(f"{name} never caught up: {out!r} {err!r}")
                time.sleep(0.01)

    try:
        wait(1)
        send("write", text="appended 1\nappended 2\n")
        wait(3)
        send("write", text="written in ")
        time.sleep(0.3)  # GNU prints the fragment now; followtail waits for the newline
        send("write", text="two parts\n")
        wait(4)
        shutil.copyfile(log, work / "app.log.1")  # logrotate copytruncate
        with open(log, "r+b") as handle:
            handle.truncate(0)
        wait(4, "file truncated")
        send("write", text="after copytruncate\n")
        wait(5)
        send("close")
        fresh = work / "app.log.new"
        fresh.write_bytes(b"after create rotation\n")
        os.link(log, work / "app.log.2")
        os.replace(fresh, log)  # the name moves to a new file in one step
        wait(6)
        os.remove(log)
        wait(6, "inaccessible")
        send("write", text="recreated\n")
        wait(7, "appeared")
        send("burst", prefix="burst ", start=0, count=200, pause=0)
        wait(207)
    finally:
        assert writer.stdin is not None
        writer.stdin.close()  # end of input: the writer closes its file and exits
        writer.wait(GUARD)
        assert writer.stdout is not None
        writer.stdout.close()
        for proc in procs.values():
            proc.terminate()
            proc.wait(GUARD)
        for out, err in files.values():
            out.close()
            err.close()
    result = {}
    for name in followers:
        result[f"{name}_out"] = (work / f"{name}.out").read_text()
        result[f"{name}_err"] = (work / f"{name}.err").read_text()
    shutil.rmtree(work)
    print(json.dumps(result))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
