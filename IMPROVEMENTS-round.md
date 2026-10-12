# Improvement round: followtail 0.2.0

Progress:
- [x] Repo read, main has the real 0.1.0 implementation
- [x] Ground truth fetched and cited (see Sources)
- [x] Brainstorm ranked (this file)
- [x] Core: held descriptor, drain before switching, follow by name or by descriptor
- [x] Typed events, multiple files, Follower step API
- [x] Start positions (end, start, last N lines), partial-line policy, encoding errors
- [x] Stop signal, total timeout, injectable clock and sleep
- [x] Windows shared open (FILE_SHARE_DELETE)
- [x] Async iterators
- [x] CLI (`followtail -F file -n N`)
- [x] Docs: docstrings, README, GUIDE, CHANGELOG, version 0.2.0
- [x] Contract test and real writer process scenarios
- [x] GNU tail -F oracle in WSL
- [ ] Real e2e: wheel, throwaway venv, installed script with a live writer
- [ ] Gates green (ruff format, ruff check, mypy --strict src, pytest)
- [x] PR opened (#2)
- [ ] Independent review and fixes
- [ ] Guard CLEAN after fixes

## Sources (fetched 2026-10-12)

- GNU coreutils `tail` invocation:
  https://www.gnu.org/software/coreutils/manual/html_node/tail-invocation.html.
  `--follow=descriptor` is the default and keeps following "even after it has been
  unlinked"; it "is not useful if you're tracking a log file that may be rotated
  (removed or renamed, then reopened). In that case, use --follow=name". "No matter
  which method you use, if the tracked file is determined to have shrunk, tail prints a
  message saying the file has been truncated and resumes tracking from the start of the
  file". `-F` "is the same as --follow=name --retry". Without `--retry` an inaccessible
  file is reported and "never checks it again"; with `--follow=descriptor`, `--retry`
  "only affects the initial open of the file". `-n` counts lines from the end, `-n +N`
  starts at line N. The default sleep interval is 1.0 s.
- logrotate(8): https://man7.org/linux/man-pages/man8/logrotate.8.html. `create`:
  "Immediately after rotation (before the postrotate script is run) the log file is
  created (with the same name as the log file just rotated)". `copytruncate`: "Truncate
  the original log file to zero size in place after creating a copy, instead of moving
  the old log file", for programs that keep appending to the same descriptor; "there is
  a very small time slice between copying the file and truncating it, so some logging
  data might be lost".
- `CreateFileW`:
  https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew.
  `FILE_SHARE_DELETE` "Enables subsequent open operations on a file or device to request
  delete access. Otherwise, no process can open the file or device if it requests delete
  access." Python's built-in `open` does not pass it, so a reader holding a log open with
  `open()` blocks the writer from renaming or deleting it.
- Observed with GNU coreutils 9.7 `gnutail` in WSL Ubuntu 26.04 (the default `tail`
  there is uutils, so the GNU binary is used explicitly): in polling mode a rename then
  recreate prints "'f' has been replaced;  following new file" after draining what was
  appended to the old file; with inotify the same rotation is reported as "has become
  inaccessible" then "has appeared" and a line written to the old descriptor after the
  rename is lost. Truncation prints "f: file truncated".

## Positioning

0.1.0 reopened the file by name on every poll. That loses whatever the writer appended
between the last poll and a rename, cannot follow a deleted file by descriptor, and on
Windows its plain `open()` would block rotation if the handle were kept. 0.2.0 holds one
shared descriptor per file and checks the name on every poll, which is how GNU `tail -F`
behaves in polling mode, while keeping the 0.1.0 call signature and defaults.

## Ranked improvements

1. Hold the descriptor and drain it before switching: on rename and recreate, read the
   old file to its end, then follow the new one from its start. Lossless for the usual
   `create` rotation.
2. `by="name"` (default, as 0.1.0) or `by="descriptor"` (keep reading an unlinked or
   renamed file, still detect truncation), plus `retry` (`-F` vs `-f`).
3. Typed events: `Line`, `Truncated`, `Rotated`, `Missing`, `Appeared`, via
   `follow_events`. Multiple files in one call, events carry the path.
4. `Follower`: one non-blocking `poll()` step for callers with their own loop
   (selectors, GUI timers, tests), with `close()` and context manager support.
5. Start positions: `lines=N` (last N lines, read backwards, GNU counting of an
   unterminated last line), `from_start`, default end. `read_last_lines` helper.
6. Partial-line policy: `partial="wait"` (default) holds a fragment until its newline or
   until its file ends (rotation, truncation, deletion); `partial="flush"` also emits it
   after one idle poll. `Line.complete` tells them apart. `max_line` caps the buffer.
7. Encoding: `errors` passed to the decoder; encodings where newline is not the byte
   `\n` (UTF-16, UTF-32) are rejected up front instead of producing garbage.
8. `stop` (a `threading.Event` or a callable) and total `timeout` with injectable
   `clock`; waits on the event when it is one so stopping is prompt.
9. Windows: open with `FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE` so the
   writer can still rotate or delete the file while it is followed. Limits documented.
10. `afollow` and `afollow_events` async iterators with an injectable async sleep.
11. Bounded reads per poll so replaying a huge file does not load it all at once.
12. Docstrings on every public name, README refresh, GUIDE.md with recipes.
13. CLI `followtail [-f | -F | --follow=name|descriptor] [-n [+]N] [-s SEC] FILE...`
    with GNU style notices on stderr, headers for several files, `--timeout`, clean
    Ctrl+C and closed pipe handling.

Kept as is: the `follow` signature, its defaults and its line semantics (newline and a
trailing carriage return stripped). Behaviour fix: a file that appears after following
started is read from its first byte, as `tail -F` does, instead of from its size at
first sight.
