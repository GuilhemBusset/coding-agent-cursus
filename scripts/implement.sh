#!/usr/bin/env bash
# Terminal entry point of the implement loop (/implement in Claude Code, $implement in Codex).
#
#   scripts/implement.sh plan 10      # what a run on issue or epic #10 would do (read-only)
#   scripts/implement.sh status 10    # progress of the run for #10
#   scripts/implement.sh stop 10      # ask that run to stop at the next safe point
#
# The engine lives in tools/implementation-loop/ and needs Python 3.11+, git and an
# authenticated GitHub CLI. See docs/adr/0008-implement-loop.md.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$repo_root/tools/implementation-loop/implement.py" "$@"
