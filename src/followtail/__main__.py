"""Run the command line tool with ``python -m followtail``."""

from __future__ import annotations

import sys

from ._cli import main

sys.exit(main())
