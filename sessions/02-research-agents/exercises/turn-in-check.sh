#!/usr/bin/env bash
# The shared turn-in runs this from the session folder. Git Bash on Windows.
set -euo pipefail
uv run --locked python -m exercises.fixed.turn_in_check
