"""Typed events reported while following files."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Line:
    """One line of text read from ``path``, without its newline or trailing ``\\r``.

    ``complete`` is ``False`` for a fragment emitted without its newline: the rest of a
    file that was rotated, truncated or deleted mid line, a fragment flushed by
    ``partial="flush"``, or a slice cut by ``max_line``.
    """

    path: str
    text: str
    complete: bool = True


@dataclass(frozen=True, slots=True)
class Truncated:
    """``path`` shrank below the read position; reading resumes from its start.

    This is what ``logrotate``'s ``copytruncate`` mode, ``: > file`` and opening the
    file with ``"w"`` look like to a follower.
    """

    path: str


@dataclass(frozen=True, slots=True)
class Rotated:
    """The name ``path`` now refers to a different file (rename and recreate).

    The old file was read to its end before this event; the new one is read from its
    first byte. Only reported when following by name.
    """

    path: str


@dataclass(frozen=True, slots=True)
class Missing:
    """``path`` cannot be opened: it does not exist yet, or it was deleted or renamed.

    With ``retry=True`` the name keeps being checked and :class:`Appeared` follows once
    it is back. With ``retry=False`` the file is dropped.
    """

    path: str


@dataclass(frozen=True, slots=True)
class Appeared:
    """``path`` exists again after a :class:`Missing`; it is read from its first byte."""

    path: str


Event = Line | Truncated | Rotated | Missing | Appeared
"""Any event yielded by :func:`followtail.follow_events` and :class:`Follower`."""
