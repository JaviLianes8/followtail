# followtail

Follow a growing text file like tail -f, surviving log rotation, yielding new complete lines

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

`follow` yields a line only once its terminating newline has arrived, so a half written
record is buffered until it is complete. It reopens the file on every poll, so it keeps
following across log rotation: a rename and recreate (new inode) or a truncate (shrunk
size) both reset to the start of the fresh file.

```python
# Replay the file from the top, then keep following.
for line in follow("app.log", from_start=True):
    handle(line)

# Poll four times a second instead of the default two.
for line in follow("app.log", poll=0.25):
    handle(line)
```

Options (all keyword only):

- `poll` (default `0.5`): seconds to wait between reads while the file is idle.
- `from_start` (default `False`): read existing content before following new writes.
- `encoding` (default `"utf-8"`): text encoding used to decode each line.
- `max_idle` (default `None`): stop after this many consecutive idle polls. Handy in
  tests so the iterator terminates instead of blocking forever.
- `sleep` (default `time.sleep`): the wait callable, injectable for tests.

Lines are returned without their trailing newline, and a trailing carriage return (from
CRLF files) is stripped.

## Why

Tailing a log in Python usually means either shelling out to `tail -f` or reaching for
[`tailer`](https://pypi.org/project/tailer/), which has had no release since 2015 and
ships no type hints. `followtail` is a small, zero dependency, fully typed take: one
generator, `mypy --strict` clean, that handles rotation and partial lines so you do not
reimplement them each time.

## License

MIT. See [LICENSE](LICENSE).

## Links

- Website: https://lianes8studio.com
- GitHub: https://github.com/JaviLianes8
- LinkedIn: https://www.linkedin.com/in/jlianes/
