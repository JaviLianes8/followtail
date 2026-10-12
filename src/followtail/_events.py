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
    """``path`` cannot be read: it does not exist (yet), or was deleted or renamed.

    ``reason`` is the system message, in the words of GNU ``tail``: ``"No such file
    or directory"``, ``"Permission denied"`` (also a file another process holds
    exclusively) or ``"Is a directory"``. With ``retry=True`` the name keeps being
    checked and :class:`Appeared` follows once it can be read; a reason change is
    reported again. With ``retry=False``, and always for a directory, the path is
    dropped.
    """

    path: str
    reason: str = "No such file or directory"


@dataclass(frozen=True, slots=True)
class Appeared:
    """``path`` exists again after a :class:`Missing`; it is read from its first byte."""

    path: str


Event = Line | Truncated | Rotated | Missing | Appeared
"""Any event yielded by :func:`followtail.follow_events` and :class:`Follower`."""
