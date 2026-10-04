#!/usr/bin/env bash
# CI-side layer behind the implement loop's trusted verifier (docs/adr/0008-implement-loop.md).
# Acceptance checks that the loop committed (commits carrying the trailer
# "Loop-Phase: acceptance-checks") must not be changed by any later commit on the same branch,
# except by a newer acceptance-checks commit (the loop re-locks checks when an issue's
# requirements change or a reproduced defect is amended). A newer acceptance-checks commit may
# also retire checks a new design no longer uses with "Loop-Unlocks: <path>" trailers
# (docs/adr/0011-autonomous-implement-loop.md); from that commit on they are no longer locked.
# Merge commits are ignored: they only bring in main.
#
#   bash scripts/check-loop-guard.sh <base-sha> <head-sha>
set -euo pipefail

base="$1"
head="$2"
trailer='^Loop-Phase: acceptance-checks$'
status=0

is_checks_commit() { git log -1 --format=%B "$1" | grep -q "$trailer"; }
unlocks() { git log -1 --format=%B "$1" | sed -n 's/^Loop-Unlocks: //p'; }

for locker in $(git rev-list --reverse --no-merges --grep="$trailer" "$base..$head"); do
  # what this commit wrote, minus what it deleted or retired
  locked="$(git diff-tree --no-commit-id --name-only --diff-filter=d -r "$locker")"
  own="$(unlocks "$locker")"
  if [ -n "$own" ]; then
    locked="$(grep -Fxv -f <(printf '%s\n' "$own") <<<"$locked" || true)"
  fi
  for later in $(git rev-list --reverse --no-merges "$locker..$head"); do
    if is_checks_commit "$later"; then
      released="$(unlocks "$later")"
      if [ -n "$released" ]; then
        locked="$(grep -Fxv -f <(printf '%s\n' "$released") <<<"$locked" || true)"
      fi
      continue
    fi
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
