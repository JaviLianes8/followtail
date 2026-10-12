"""When to poll again, and when to stop: idle limit, stop signal, total timeout."""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from typing import Protocol


class SupportsIsSet(Protocol):
    """Anything with ``is_set()``, such as ``threading.Event`` or ``asyncio.Event``."""

    def is_set(self) -> bool: ...


StopSignal = SupportsIsSet | Callable[[], bool]
"""A ``threading.Event`` (or anything with ``is_set()``) or a callable returning a bool."""


class Pacer:
    """Decide, after each poll, whether to stop or how long to wait before the next."""

    def __init__(
        self,
        poll: float,
        max_idle: int | None,
        stop: StopSignal | None,
        timeout: float | None,
        clock: Callable[[], float],
    ) -> None:
        _non_negative("poll", poll)
        if timeout is not None:
            _non_negative("timeout", timeout)
        if max_idle is not None and (isinstance(max_idle, bool) or max_idle < 0):
            raise ValueError(f"max_idle must be >= 0, got {max_idle!r}")
        if stop is not None and not hasattr(stop, "is_set") and not callable(stop):
            raise TypeError("stop must have is_set() or be callable")
        self._poll = poll
        self._max_idle = max_idle
        self._stop = stop
        self._clock = clock
        self._deadline = None if timeout is None else clock() + timeout
        self._idle = 0

    @property
    def waiter(self) -> Callable[[float], object] | None:
        """``stop.wait`` when the stop signal is a ``threading.Event``, so it wakes early."""
        if isinstance(self._stop, threading.Event):
            return self._stop.wait
        return None

    def stopped(self) -> bool:
        """True once the stop signal is set or the timeout has passed."""
        if self._stop is not None and _is_set(self._stop):
            return True
        return self._deadline is not None and self._clock() >= self._deadline

    def next_wait(self, moved: bool) -> float | None:
        """Seconds to wait before the next poll (0 after a poll that moved); None to stop."""
        if self.stopped():
            return None
        if moved:
            self._idle = 0
            return 0.0
        self._idle += 1
        if self._max_idle is not None and self._idle >= self._max_idle:
            return None
        if self._deadline is None:
            return self._poll
        return max(0.0, min(self._poll, self._deadline - self._clock()))


def _is_set(stop: StopSignal) -> bool:
    is_set = getattr(stop, "is_set", None)
    if is_set is not None:
        return bool(is_set())
    return bool(stop())  # type: ignore[operator]


def _non_negative(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number, got {value!r}")
    if math.isnan(value) or value < 0:
        raise ValueError(f"{name} must be >= 0, got {value!r}")
