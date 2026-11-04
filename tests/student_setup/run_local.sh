#!/usr/bin/env bash
# Run the student setup for real on this Linux machine, the way the CI jobs do (run_twice.sh),
# without touching your own HOME: an empty HOME under a temporary folder, and a PATH with only
# the system's folders, so only the system's git, gh and curl are there to start with.
#
#   bash tests/student_setup/run_local.sh        # from the repository root
#
# The course it clones is a standalone snapshot of this working tree (tracked and untracked
# files, committed in a new repository), so uncommitted changes are tested too and nothing is
# written to this clone's git. It downloads uv, mise, Claude Code, Codex, Python and every
# session's packages: a few minutes. Nothing is logged in (--no-login).
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
work=$(mktemp -d "${TMPDIR:-/tmp}/student-setup-local.XXXXXX")
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/src" "$work/home"

# Tracked files deleted in the working tree are listed but missing: cp skips them.
cd "$repo"
git ls-files -z --cached --others --exclude-standard | { xargs -0 cp --parents -a -t "$work/src" 2>/dev/null; true; }
git -C "$work/src" init -q -b main
git -C "$work/src" add -A
git -C "$work/src" -c user.name=snapshot -c user.email=snapshot@example.com commit -q -m snapshot

env -i HOME="$work/home" PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 TERM="${TERM:-dumb}" USER="${USER:-student}" TMPDIR="$work" \
  bash "$work/src/tests/student_setup/run_twice.sh" "$work/src"
