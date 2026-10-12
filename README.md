# followtail

Follow a growing text file like `tail -F`, surviving log rotation, yielding new complete
lines. Typed, zero dependencies, sync and async, with a command line tool.

## Install

```
pip install followtail
```

## Usage

```python
from followtail import follow

# Blocks forever, printing each new line as the log grows.
for line in follow("/var/log/app.log"):
    print(line)
```

`follow` yields a line only once its newline has arrived, so a half written record is
held until it is complete. It keeps one descriptor open and checks the name on every
poll, so it survives every rotation style logrotate performs:

- **create** (rename, then a new file under the name): the old file is read to its
  end first, then the new one from its first byte. Nothing appended just before the
  rotation is lost.
- **copytruncate** (the file is copied, then truncated in place): the shrink is
  detected and reading resumes from the start.
- **deletion and recreation**: the follower waits for the name to come back, then
  reads the new file from its first byte.

```python
# The last 10 lines, then keep following.
for line in follow("app.log", lines=10):
    handle(line)

# Stop after a minute, or when another thread sets the event.
import threading
stop = threading.Event()
for line in follow("app.log", timeout=60, stop=stop):
    handle(line)
```

### Events and several files

```python
from followtail import Line, Rotated, Truncated, follow_events

for event in follow_events(["api.log", "worker.log"], lines=0):
    match event:
        case Line(path, text):
            print(f"{path}: {text}")
        case Rotated(path) | Truncated(path):
            print(f"{path} was rotated")
```

Events are `Line`, `Truncated`, `Rotated`, `Missing` and `Appeared`; each carries the
path it belongs to.

### Async

```python
from followtail import afollow

async for line in afollow("app.log", lines=10):
    await publish(line)
```

### Your own loop

`Follower` does one non-blocking step per `poll()`, for GUI timers, selectors or tests:

```python
from followtail import Follower

with Follower("app.log") as follower:
    for event in follower.poll():
        ...
```

### Options

All keyword only, shared by `follow`, `follow_events`, `afollow`, `afollow_events`:

| Option | Default | Meaning |
| --- | --- | --- |
| `poll` | `0.5` | seconds to wait after a poll that found nothing |
| `by` | `"name"` | `"name"` follows the path (`tail -F`), `"descriptor"` the file first opened (`tail -f`) |
| `retry` | `True` | keep waiting for a missing file; `False` drops it |
| `from_start` | `False` | read existing content first |
| `lines` | `None` | start this many lines before the end (`tail -n`) |
| `partial` | `"wait"` | `"flush"` also emits a fragment left unterminated for a whole poll |
| `encoding`, `errors` | `"utf-8"`, `"strict"` | decoding; use `errors="replace"` for untrusted logs |
| `max_line` | `None` | cut longer lines into fragments of at most this many bytes |
| `max_idle`, `stop`, `timeout` | `None` | ways to end the iteration |
| `sleep`, `clock` | stdlib | injectable for tests |

Lines come without their newline; one trailing carriage return (CRLF files) is removed.
`read_last_lines(path, n)` returns the last lines of a file without following it.

## Command line

```
followtail -n 5 app.log              print the last 5 lines and exit
followtail -F /var/log/app.log       follow by name, across rotation and deletion
followtail -n 50 -F app.log          the last 50 lines, then follow
followtail -n +1 -f build.log        the whole file, then follow the open file
followtail -F a.log b.log            several files, with ==> name <== headers
followtail -F app.log --timeout 60   stop following after a minute
```

The options and the notices on stderr follow GNU `tail` (`file truncated`, `has been
replaced;  following new file`, `has become inaccessible`, `has appeared`). Exit status
is 1 on errors, 130 on Ctrl+C; a closed pipe (`| head`) ends it quietly.

## Windows

followtail opens files with `FILE_SHARE_DELETE`, so the writer can still rename, delete
or truncate a file while it is followed (a reader using the built-in `open()` would
block that). Two limits come from Windows itself: a writer that holds its log open with
the built-in `open()` cannot be renamed under it (use copytruncate, or reopen the log
after rotating), and replacing the followed name in one step (`os.replace` onto it)
fails while it is open; rename the old file away, then create the new one.

## Why

Tailing a log in Python usually means shelling out to `tail -f` or reaching for
[`tailer`](https://pypi.org/project/tailer/), which has had no release since 2015,
ships no type hints and does not survive rotation. followtail behaves like GNU `tail -F`
(checked against it line for line and notice for notice), loses nothing across a create
rotation, works the same on Windows, and is `mypy --strict` clean.

More recipes and the exact semantics: [GUIDE.md](GUIDE.md).

## License

MIT. See [LICENSE](LICENSE).

## Links

- Website: https://lianes8studio.com
- GitHub: https://github.com/JaviLianes8
- LinkedIn: https://www.linkedin.com/in/jlianes/
