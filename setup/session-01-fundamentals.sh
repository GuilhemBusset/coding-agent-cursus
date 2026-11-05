#!/usr/bin/env bash
# Set up the course's sessions on a clone: a wrapper over the student setup's shared step,
# setup/student/prepare.py. It keeps this name because Session 1's README and pre-work page give
# this command; it now prepares every session, not only Session 1.
#
# Activates the clone's git hooks (as setup/git-hooks.sh does), then, in every session that has a
# mise.toml, a pyproject.toml and a uv.lock: `mise trust`, `mise install` (the Python and uv the
# session pins) and `mise exec -- uv sync --locked` (its runtime dependencies from uv.lock; the
# build-only `fixtures` group is not installed). It does not run the setup check. Needs mise and
# uv, which the pre-work installs; setup/student/install.sh installs everything from scratch.
# Paths are resolved from this script's location, so pass its path from any directory. Safe to
# run repeatedly.
#
#   bash setup/session-01-fundamentals.sh            # from the repo root
#   bash ../../setup/session-01-fundamentals.sh      # from inside a session
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for tool in mise uv; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "[setup] $tool is required: install it with 'Install the tools' on the pre-work page (sessions/01-fundamentals/exercises/00-prework.html), or run setup/student/install.sh" >&2
    exit 1
  fi
done

uv run --no-project --python 3.12 python "$repo/setup/student/prepare.py" --repo "$repo" --no-check
echo "[setup] Sessions ready. Run Session 1's tests with: cd sessions/01-fundamentals && uv run pytest"
