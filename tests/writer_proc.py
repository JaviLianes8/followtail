"""A real writer process for the tests, driven by JSON commands on stdin.

Each command is acknowledged with ``ok`` on stdout once its bytes are flushed to the
operating system, so a test knows exactly what is on disk before it polls.

Commands: ``{"op": "write", "text": ...}`` appends (the file is kept open between
writes, in append mode, like a logger); ``{"op": "reopen"}`` closes and reopens the
name (what a logger does on SIGHUP after a ``create`` rotation); ``{"op": "close"}``;
``{"op": "burst", "prefix": ..., "start": n, "count": n, "pause": s}`` writes numbered
lines with a short pause between them, flushing each, without waiting for the reader.
"""

from __future__ import annotations

import json
import sys
import time
from typing import BinaryIO


def main(path: str) -> None:
    handle: BinaryIO | None = None
    for raw in sys.stdin:
        command = json.loads(raw)
        op = command["op"]
        if op in ("write", "burst") and handle is None:
            handle = open(path, "ab")  # noqa: SIM115 - held open across commands
        if op == "write":
            assert handle is not None
            handle.write(command["text"].encode("utf-8"))
            handle.flush()
        elif op == "burst":
            assert handle is not None
            for number in range(command["start"], command["start"] + command["count"]):
                handle.write(f"{command['prefix']}{number}\n".encode())
                handle.flush()
                time.sleep(command["pause"])
        elif op in ("reopen", "close") and handle is not None:
            handle.close()
            handle = open(path, "ab") if op == "reopen" else None  # noqa: SIM115
        elif op == "exit":
            break
        sys.stdout.write("ok\n")
        sys.stdout.flush()
    if handle is not None:
        handle.close()


if __name__ == "__main__":
    main(sys.argv[1])
