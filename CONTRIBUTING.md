# Contributing

Thanks for taking the time. This project keeps a small, predictable shape.

## Setup

```
pip install -r requirements-dev.txt
```

## Before you open a pull request

- Keep public API in `src/followtail/__init__.py`; internals live in `_`-prefixed modules.
- Add a test for the behaviour you change. Unit tests inject `sleep` and `clock`; the
  promise, rotation and oracle tests use real files and a real writer process, and
  wait on conditions (bounded only as a guard), never on fixed delays.
- The GNU `tail` oracle runs inside WSL on Windows (or natively on Linux) and is
  skipped with a reason when GNU coreutils `tail` is not available.
- Run `scripts/check.ps1` (format, lint, types, tests) and make sure it passes.
- One logical change per commit, imperative subject line.

Open an issue first if the change is large or shifts the public API.
