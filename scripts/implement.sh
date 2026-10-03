#!/usr/bin/env bash
# Terminal entry point of the implement loop (/implement in Claude Code, $implement in Codex).
#
#   scripts/implement.sh doctor [--smoke]               # check the toolchain a run needs
#   scripts/implement.sh plan 10                         # what a run on #10 would do (read-only)
#   scripts/implement.sh run 10 --operator claude --yes  # run it (merges its own PRs); resumes
#   scripts/implement.sh status 10                       # progress and cost of the run for #10
#   scripts/implement.sh stop 10                         # stop that run at its next safe point
#
# The engine lives in tools/implementation-loop/ and needs Python 3.11+, git, an authenticated
# GitHub CLI, and both the claude and codex CLIs. See docs/adr/0008-implement-loop.md.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$repo_root/tools/implementation-loop/implement.py" "$@"
