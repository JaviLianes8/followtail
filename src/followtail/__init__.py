"""Follow a growing text file like tail -f, surviving log rotation, yielding new complete lines."""

from __future__ import annotations

from ._follow import DEFAULT_POLL, follow

__version__ = "0.1.0"

__all__ = ["DEFAULT_POLL", "follow"]
