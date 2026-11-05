"""Puts setup/student on sys.path, so the tests import prepare.py as ty resolves it (ty.toml)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "setup/student"))
