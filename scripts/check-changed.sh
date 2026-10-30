#!/usr/bin/env bash
# Run only the checks a change can affect (tools/test-impact/impact.toml, docs/adr/0013): the
# change is everything since the merge base with origin/main, including staged, unstaged and
# untracked files. Needs Python 3.11 or newer, plus the tools of whatever it selects.
#
#   scripts/check-changed.sh               run them
#   scripts/check-changed.sh plan          show what would run, and why
#   scripts/check-changed.sh --base REF    measure the change against REF instead
#   scripts/check-changed.sh --all         run everything
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "${1:-}" = plan ]; then
  shift
  exec python3 tools/test-impact/impact.py plan "$@"
fi
exec python3 tools/test-impact/impact.py run "$@"
