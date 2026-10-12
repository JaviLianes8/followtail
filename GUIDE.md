# followtail guide

Exact semantics and recipes. The README has the short version.

## How a file is followed

Each followed path keeps one open descriptor and a read position. Every poll:

1. If no descriptor is held, try to open the path. A file that exists when following
   starts is positioned by `from_start` / `lines` (default: its end). A file that
   appears later is read from its first byte, as GNU `tail -F` does.
2. If the file is now shorter than the read position, it was truncated: a pending
   fragment is emitted, `Truncated` is reported and reading restarts at byte 0.
3. Read what was appended, at most 1 MiB per file per poll, so replaying a huge file
   never loads it at once (the next poll follows immediately while data is pending).
4. With `by="name"`, check the name. If it now leads to a different file (another
   device and inode pair) the old file is read to its end, its pending fragment is
   emitted, `Rotated` is reported and the new file is read from its first byte. If the
   name is gone, the old file is drained the same way and `Missing` is reported; with
   `retry=True` the name is tried again on every poll and `Appeared` is reported when it
   is back.

With `by="descriptor"` step 4 never runs: the file first opened is followed even after
it is renamed or deleted, like `tail -f`. Truncation is still detected.

This is what GNU `tail -F` does in polling mode. The tests run GNU coreutils `tail`
(polling and inotify) and followtail on the same file with the same writer and require
the same output and the same notices.

### What polling cannot see

- A truncation followed, before the next poll, by writes that grow the file past the
  old read position looks like plain growth. GNU `tail` has the same limit. Keep the
  poll interval short if writers truncate and refill quickly.
- Two rotations between two polls skip the middle file.
- logrotate documents that `copytruncate` loses lines written between the copy and the
  truncation; no reader can recover those.

## Lines and fragments

Bytes are split on `\n` before decoding, which is correct for UTF-8, ASCII, Latin-1,
cp1252 and other encodings where a newline is the single byte `0x0A`. UTF-16 and UTF-32
are rejected with `ValueError`. A multi-byte character split across two writes is
decoded whole, because a line is only decoded once it is complete.

The `partial` policy decides when an unterminated fragment is emitted:

| Situation | `"wait"` (default) | `"flush"` |
| --- | --- | --- |
| newline arrives | whole line | whole line |
| file rotated, truncated or deleted | fragment, `complete=False` | same |
| file idle for a full poll | held | fragment, `complete=False` |
| iteration ends (stop, timeout, idle) | dropped | fragment, `complete=False` |

`"flush"` suits prompts and progress output that never end in a newline. After a
flushed fragment, the rest of that line arrives as its own `Line`.

`max_line=N` caps memory for files that might never contain a newline: longer lines are
cut into fragments of at most N bytes (never inside a UTF-8 character).

### Decode errors

With `errors="strict"` an undecodable line raises `UnicodeDecodeError` from the
iterator, which ends it. With `Follower.poll()` the bad line is skipped and the next
call carries on with everything queued after it. For logs you do not control, pass
`errors="replace"` (the command line default) or `"backslashreplace"`.

## Ending the iteration

- `max_idle=N`: stop after N polls in a row that found nothing.
- `stop`: a `threading.Event`, an `asyncio.Event` or any callable returning a bool. A
  `threading.Event` is also used for the wait, so setting it wakes the follower at once.
- `timeout`: total seconds, measured on `clock` (default `time.monotonic`). The last
  wait is cut short so it never sleeps past the deadline.

On a stop or a timeout one final poll runs, so lines written just before are delivered.
Breaking out of the loop, or calling `close()` on the generator, releases the
descriptors.

## Recipes

### Wait for a line, with a deadline

```python
from followtail import follow


def wait_for(path, needle, seconds):
    for line in follow(path, timeout=seconds):
        if needle in line:
            return line
    raise TimeoutError(f"{needle!r} not seen in {path} within {seconds}s")
```

### Follow in a background thread

```python
import queue, threading
from followtail import follow_events

stop = threading.Event()
events = queue.Queue()


def run():
    for event in follow_events("app.log", stop=stop):
        events.put(event)


threading.Thread(target=run, daemon=True).start()
...
stop.set()
```

### Several files in asyncio

```python
from followtail import Line, afollow_events


async def ship(paths):
    async for event in afollow_events(paths, lines=0, errors="replace"):
        if isinstance(event, Line):
            await send(event.path, event.text)
```

### Drive it from your own loop

```python
from followtail import Follower

follower = Follower("app.log", lines=20)


def on_timer():
    for event in follower.poll():
        render(event)


...
follower.close()
```

### Testing code that follows files

Inject `sleep` (and `clock` when using `timeout`) to run without real time; a fake
sleep can append to the file to script what the writer does:

```python
def test_reads_new_lines(tmp_path):
    log = tmp_path / "a.log"
    log.write_text("")

    def sleep(_):
        log.write_text("hello\n")

    assert list(follow(log, max_idle=2, sleep=sleep)) == ["hello"]
```

## Windows

Files are opened through `CreateFileW` with `FILE_SHARE_READ | FILE_SHARE_WRITE |
FILE_SHARE_DELETE`. While followtail holds a log, the writer can still append, truncate,
rename it away and delete it, and create a new file under the same name. Windows itself
imposes two limits:

- A writer that keeps its log open with Python's built-in `open()` (no share delete)
  cannot have it renamed while it writes. Use copytruncate for such writers, or have
  them reopen the file after the rotation.
- `os.replace(new, log)` (`MoveFileEx` with replace) fails while `log` is open by any
  process, whatever the share mode. Rotate in two steps: rename the old file away, then
  create the new one.

## Command line

`followtail [-f | -F | --follow[=name|descriptor]] [--retry] [-n [+]N] [-s SECONDS]
[--timeout SECONDS] [--partial wait|flush] [--encoding E] [--errors H] [-q | -v] FILE...`

- Without `-f` / `-F` it prints the last N lines (default 10) and exits; `-n +N` starts
  at line N. An unterminated last line is printed without a newline.
- `-f` follows the descriptor; `-F` is `--follow=name --retry`. Without retry a file
  that cannot be opened is reported and dropped, and the tool exits 1 with `no files
  remaining` once none is left.
- Notices on stderr use the GNU wording. Lines are written and flushed as they arrive,
  so `followtail -F app.log | grep ERROR` sees each line at once.
- Exit status: 0, 1 on any error (usage included), 130 on Ctrl+C. A closed output pipe
  ends the tool quietly with 0.
