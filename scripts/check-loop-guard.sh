#!/usr/bin/env bash
# CI-side layer behind the implement loop's trusted verifier (docs/adr/0008-implement-loop.md).
# Acceptance checks that the loop committed (commits carrying the trailer
# "Loop-Phase: acceptance-checks") must not be changed by any later commit on the same branch,
# except by a newer acceptance-checks commit (the loop re-locks checks when an issue's
# requirements change). Merge commits are ignored: they only bring in main.
#
#   bash scripts/check-loop-guard.sh <base-sha> <head-sha>
set -euo pipefail

base="$1"
head="$2"
trailer='^Loop-Phase: acceptance-checks$'
status=0

is_checks_commit() { git log -1 --format=%B "$1" | grep -q "$trailer"; }

for locker in $(git rev-list --reverse --no-merges --grep="$trailer" "$base..$head"); do
  locked="$(git diff-tree --no-commit-id --name-only -r "$locker")"
  for later in $(git rev-list --reverse --no-merges "$locker..$head"); do
    is_checks_commit "$later" && continue
    changed="$(git diff-tree --no-commit-id --name-only -r "$later")"
    while IFS= read -r file; do
      [ -n "$file" ] || continue
      if grep -Fxq -- "$file" <<<"$changed"; then
        echo "::error file=$file::$file was locked by acceptance-checks commit ${locker:0:7} but changed by ${later:0:7}"
        status=1
      fi
    done <<<"$locked"
  done
done

if [ "$status" -eq 0 ]; then
  echo "[loop-guard] no locked acceptance check was changed after it was committed"
fi
exit "$status"
