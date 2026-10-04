#!/usr/bin/env bash
# Set up Session 1 (sessions/01-fundamentals/) on a fresh clone.
#
# Installs the session's pinned Python and uv through mise (mise.toml), then
# creates the session's .venv/ from its committed uv.lock. Only the runtime
# dependencies are installed; the build-only `fixtures` group is not. Paths are
# resolved from this script's location, so pass its path from any directory.
# Safe to run repeatedly.
#
#   bash setup/session-01-fundamentals.sh            # from the repo root
#   bash ../../setup/session-01-fundamentals.sh      # from inside the session
set -euo pipefail

session_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../sessions/01-fundamentals" && pwd)"
cd "$session_dir"

if ! command -v mise >/dev/null 2>&1; then
  echo "[setup] mise is required: install it from https://mise.jdx.dev/getting-started.html" >&2
  exit 1
fi

mise trust mise.toml
mise install
mise exec -- uv sync --locked

echo "[setup] Session 1 ready. Run its tests with: cd sessions/01-fundamentals && uv run pytest"
