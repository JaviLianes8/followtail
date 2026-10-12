"""Command line: print the end of files and follow them, like GNU ``tail -f`` / ``-F``."""

from __future__ import annotations

import argparse
import contextlib
import errno
import io
import os
import sys
from collections.abc import Iterator, Sequence
from typing import Literal, NoReturn

from ._cliout import PROG, Printer, warn
from ._events import Appeared, Line, Rotated, Truncated
from ._follow import DEFAULT_POLL, follow_events
from ._lastlines import tail_offset
from ._open import open_shared
from ._text import check_encoding

__all__ = ["build_parser", "main"]

_EXAMPLES = """\
examples:
  followtail -n 5 app.log              print the last 5 lines and exit
  followtail -F /var/log/app.log       follow by name, across rotation and deletion
  followtail -n 50 -F app.log          the last 50 lines, then follow
  followtail -n +1 -f build.log        the whole file, then follow the open file
  followtail -F a.log b.log            several files, with ==> name <== headers
  followtail -F app.log --timeout 60   stop following after a minute

-f follows the file first opened even if it is renamed or deleted (descriptor);
-F follows the name: after a rename and recreate it reads the old file to its end and
continues with the new one, and it waits for a missing file to appear. Both detect
truncation (logrotate copytruncate). Notices go to stderr; exit status 1 on errors.
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _count(text: str) -> tuple[bool, int]:
    """Parse ``-n``: ``N`` or ``-N`` for the last N lines, ``+N`` to start at line N."""
    digits = text[1:] if text[:1] in "+-" else text
    if not digits.isdigit():
        raise argparse.ArgumentTypeError(f"invalid number of lines: {text!r}")
    return text.startswith("+"), int(digits)


def _seconds(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        value = -1.0
    if not 0 <= value < float("inf"):
        raise argparse.ArgumentTypeError(f"invalid number of seconds: {text!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    """The argument parser, exposed for documentation and tests."""
    from . import __version__

    parser = _Parser(
        prog=PROG,
        description="Print the last lines of each FILE; with -f or -F keep printing "
        "lines as they are appended, surviving log rotation.",
        epilog=_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add = parser.add_argument
    add("files", metavar="FILE", nargs="+", help="file to read")
    add("--version", action="version", version=f"%(prog)s {__version__}")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("-f", dest="follow", action="store_const", const="descriptor",
                      help="follow the open file (same as --follow=descriptor)")  # fmt: skip
    mode.add_argument("-F", dest="follow", action="store_const", const="name-retry",
                      help="same as --follow=name --retry")  # fmt: skip
    mode.add_argument("--follow", dest="follow", nargs="?", const="descriptor",
                      choices=["name", "descriptor"],
                      help="follow by name or by descriptor (default descriptor)")  # fmt: skip
    add("--retry", action="store_true", help="keep trying to open a file that is missing")
    add("-n", "--lines", type=_count, default=(False, 10), metavar="[+]N",
        help="print the last N lines (default 10); +N starts at line N")  # fmt: skip
    add("-s", "--sleep-interval", type=_seconds, default=DEFAULT_POLL, metavar="SECONDS",
        help=f"seconds between checks while idle (default {DEFAULT_POLL})")  # fmt: skip
    add("--timeout", type=_seconds, metavar="SECONDS", help="stop following after SECONDS")
    add("--partial", choices=["wait", "flush"], default="wait",
        help="wait: print a line once complete (default); flush: also print a fragment "
        "that stays unterminated for one interval")  # fmt: skip
    add("--encoding", default="utf-8", help="text encoding (default utf-8)")
    add("--errors", default="replace", help="decode error handler (default replace)")
    quiet = parser.add_mutually_exclusive_group()
    quiet.add_argument("-q", "--quiet", action="store_true", help="never print headers")
    quiet.add_argument("-v", "--verbose", action="store_true", help="always print headers")
    return parser


def _lines_of(path: str, from_line: bool, count: int) -> Iterator[tuple[bytes, bool]]:
    """Stream the selected lines of ``path`` as (bytes without newline, terminated)."""
    with open_shared(path) as raw:
        size = os.fstat(raw.fileno()).st_size
        raw.seek(0 if from_line else tail_offset(raw, size, count))
        skip = max(count, 1) - 1 if from_line else 0
        for line in io.BufferedReader(raw):
            if skip:
                skip -= 1
            elif line.endswith(b"\n"):
                yield line[:-2] if line.endswith(b"\r\n") else line[:-1], True
            else:
                yield line, False


def _print_once(args: argparse.Namespace, printer: Printer) -> int:
    check_encoding(args.encoding)
    status = 0
    from_line, count = args.lines
    for path in args.files:
        try:
            lines = _lines_of(path, from_line, count)
            first = next(lines, None)
        except OSError as exc:
            warn(f"cannot open '{path}' for reading: {exc.strerror or exc}")
            status = 1
            continue
        printer.header(path)
        while first is not None:
            raw, complete = first
            printer.line(path, raw.decode(args.encoding, args.errors), complete)
            first = next(lines, None)
    return status


def _follow(args: argparse.Namespace, printer: Printer) -> int:
    from_line, count = args.lines
    by: Literal["name", "descriptor"] = "descriptor" if args.follow == "descriptor" else "name"
    retry = args.retry or args.follow == "name-retry"
    events = follow_events(
        args.files, poll=args.sleep_interval, by=by, retry=retry, from_start=from_line,
        lines=None if from_line else count, partial=args.partial, encoding=args.encoding,
        errors=args.errors, timeout=args.timeout,
    )  # fmt: skip
    skip = {path: max(count, 1) - 1 if from_line else 0 for path in args.files}
    for path in args.files:
        if os.path.exists(path):
            printer.opened(path)
    with contextlib.closing(events):
        for event in events:
            if isinstance(event, (Rotated, Truncated, Appeared)):
                skip[event.path] = 0
            elif isinstance(event, Line) and event.complete and skip[event.path] > 0:
                skip[event.path] -= 1
                continue
            printer.event(event)
            printer.flush()
    if not retry and printer.missing:
        if printer.missing >= set(args.files):
            warn("no files remaining")
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line tool and return its exit status (0 ok, 1 on any error)."""
    args = build_parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")
    printer = Printer(args.verbose or (len(args.files) > 1 and not args.quiet))
    try:
        status = _follow(args, printer) if args.follow else _print_once(args, printer)
        printer.flush()
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        if isinstance(exc, BrokenPipeError) or exc.errno in (errno.EPIPE, errno.EINVAL):
            # The reader closed the pipe (``| head``): stop quietly.
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
            return 0
        warn(f"error: {exc}")
        return 1
    except (ValueError, UnicodeDecodeError) as exc:
        warn(f"error: {exc}")
        return 1
    return status


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
