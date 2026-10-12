"""Command line: print the end of files and follow them, like GNU ``tail -f`` / ``-F``."""

from __future__ import annotations

import argparse
import codecs
import errno
import io
import os
import sys
from collections.abc import Sequence
from typing import NoReturn

from . import _clirun
from ._cliout import PROG, Printer, warn
from ._follow import DEFAULT_POLL
from ._text import check_encoding

__all__ = ["build_parser", "main"]

_EXAMPLES = """\
examples:
  followtail -n 5 app.log              print the last 5 lines and exit
  followtail -F /var/log/app.log       follow by name, across rotation and deletion
  followtail -n 50 -F app.log          the last 50 lines, then follow
  followtail -n +1 -f build.log        the whole file, then follow the open file
  followtail --follow=name --retry x   same as -F
  followtail -F a.log b.log            several files, with ==> name <== headers
  followtail -F app.log --timeout 60   stop following after a minute

-f follows the file first opened even if it is renamed or deleted (descriptor);
-F follows the name: after a rename and recreate it reads the old file to its end and
continues with the new one, and it waits for a missing file to appear. Both detect
truncation (logrotate copytruncate). Notices go to stderr; exit status 1 on errors,
130 on Ctrl+C.
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
    mode.add_argument("--follow", dest="follow", action="store_const", const="descriptor",
                      help="--follow[=name|descriptor]: follow by name, or by descriptor "
                      "(the default); the value must be attached with =")  # fmt: skip
    mode.add_argument("--follow-how", dest="follow", choices=["name", "descriptor"],
                      help=argparse.SUPPRESS)  # fmt: skip
    add("--retry", action="store_true", help="keep trying to open a file that is missing")
    add("-n", "--lines", type=_count, default=(False, 10), metavar="[+]N",
        help="print the last N lines (default 10); +N starts at line N")  # fmt: skip
    add("-s", "--sleep-interval", type=_seconds, default=DEFAULT_POLL, metavar="SECONDS",
        help=f"seconds between checks while idle (default {DEFAULT_POLL})")  # fmt: skip
    add("--timeout", type=_seconds, metavar="SECONDS", help="stop following after SECONDS")
    add("--partial", choices=["flush", "wait"], default="flush",
        help="flush (default, like GNU tail): print a line still being written once it "
        "has been idle for one interval; wait: print only complete lines")  # fmt: skip
    add("--encoding", default="utf-8", help="text encoding (default utf-8)")
    add("--errors", default="replace", help="decode error handler (default replace)")
    quiet = parser.add_mutually_exclusive_group()
    quiet.add_argument("-q", "--quiet", action="store_true", help="never print headers")
    quiet.add_argument("-v", "--verbose", action="store_true", help="always print headers")
    return parser


def _gnu_style(argv: list[str]) -> list[str]:
    """Map ``--follow=HOW`` (an optional value, attached as in GNU) to a hidden option."""
    result: list[str] = []
    for index, token in enumerate(argv):
        if token == "--":
            return result + argv[index:]
        result.append("--follow-how=" + token[9:] if token.startswith("--follow=") else token)
    return result


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(_gnu_style(argv))
    try:
        check_encoding(args.encoding)
        codecs.lookup_error(args.errors)
    except (ValueError, LookupError) as exc:
        parser.error(str(exc) if isinstance(exc, ValueError) else f"unknown error handler: {exc}")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line tool and return its exit status (0 ok, 1 on any error)."""
    args = _parse(list(sys.argv[1:] if argv is None else argv))
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")
    printer = Printer(args.verbose or (len(args.files) > 1 and not args.quiet))
    try:
        run = _clirun.follow if args.follow else _clirun.print_once
        status = run(args, printer)
        printer.flush()
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        closed = isinstance(exc, BrokenPipeError) or exc.errno in (errno.EPIPE, errno.EINVAL)
        if closed and exc.filename is None:
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
