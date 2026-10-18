#!/usr/bin/env bash
# Session 1 turn-in check. `/turn-in 01`, `$turn-in 01` and `scripts/turn-in.sh 01` run it
# from sessions/01-fundamentals before committing; a non-zero exit stops the turn-in.
# The policy lives in Python (ADR 0010): a missing P01 solution.json only warns, a data or
# format problem blocks, and any other verdict is printed and turned in.
exec uv run --no-project --python 3.12 python exercises/homework-p01/p01_checker.py --turn-in
