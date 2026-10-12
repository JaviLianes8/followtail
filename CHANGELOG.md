# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0]

### Added

- `follow_events`: typed events (`Line`, `Truncated`, `Rotated`, `Missing`,
  `Appeared`) for one path or several, each carrying its path.
- `Follower`: one non-blocking `poll()` step for callers with their own loop, with
  `flush()`, `close()` and context manager support.
- `afollow` and `afollow_events`: async iterators with an injectable async sleep.
- `read_last_lines(path, n)`: the last lines of a file, read backwards in blocks.
- New keywords on `follow`: `by` (`"name"` or `"descriptor"`), `retry`, `lines`
  (start N lines before the end), `partial` (`"wait"` or `"flush"`), `errors`,
  `max_line`, `stop`, `timeout` and `clock`.
- `followtail` command line tool (`-f`, `-F`, `--follow[=HOW]`, `--retry`, `-n [+]N`,
  `-s`, `--timeout`, `--partial`, `-q`, `-v`) whose output and notices match GNU
  `tail`; `python -m followtail` too.

### Changed

- One descriptor is held per file and the name is checked on every poll. On a rename
  and recreate the old file is now read to its end before switching, so lines
  appended just before a rotation are no longer lost.
- On Windows files are opened with `FILE_SHARE_DELETE`, so a followed file can still
  be renamed or deleted by its writer.
- A file that appears after following started is read from its first byte (as
  `tail -F` does) instead of from its size when first seen.
- A fragment pending when its file is rotated, truncated or deleted is emitted as a
  `Line` with `complete=False` instead of being dropped; `follow` yields its text like
  any other line.
- A file that cannot be read for lack of permission (on Windows also one held
  exclusively by another process) is reported as `Missing(path, reason)` and retried,
  as `tail --retry` does, instead of raising `PermissionError`.
- A poll that read bytes without completing a line (a partial write) now counts as
  activity, so it resets the `max_idle` count.
- A strict decode error loses only the undecodable line: the lines read before it are
  yielded first.
- Invalid settings (including a negative `poll` or `max_idle`) raise `ValueError` or
  `TypeError` when `follow` is called rather than on the first iteration, a directory
  raises `IsADirectoryError` at that point, and
  encodings that do not encode a newline as the byte `\n` (UTF-16, UTF-32) are rejected.

## [0.1.0]

- First release.
- `follow(path, *, poll, from_start, encoding, max_idle, sleep)`: iterate new complete
  lines from a growing text file, surviving rotation by rename and recreate or truncate.
