"""Follow a growing text file like tail -f, surviving log rotation, yielding new complete lines."""

from __future__ import annotations

from ._async import afollow, afollow_events
from ._events import Appeared, Event, Line, Missing, Rotated, Truncated
from ._follow import DEFAULT_POLL, follow, follow_events
from ._follower import Follower
from ._lastlines import read_last_lines
from ._pace import StopSignal, SupportsIsSet

__version__ = "0.2.0"

__all__ = [
    "DEFAULT_POLL",
    "Appeared",
    "Event",
    "Follower",
    "Line",
    "Missing",
    "Rotated",
    "StopSignal",
    "SupportsIsSet",
    "Truncated",
    "afollow",
    "afollow_events",
    "follow",
    "follow_events",
    "read_last_lines",
]
