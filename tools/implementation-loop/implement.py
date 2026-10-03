#!/usr/bin/env python3
"""Launcher for the implement loop engine. Standard library only; Python 3.11 or newer."""

import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("implement: Python 3.11 or newer is required")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from implement_loop.cli import main  # noqa: E402

sys.exit(main())
