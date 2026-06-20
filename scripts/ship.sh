#!/usr/bin/env bash
# Portable, agent-independent core of /ship.
#
# Asserts we are on a feature branch, rebases it onto main, and pushes it with
# retry/backoff. PR creation is delegated to the calling agent (via the `gh`
# CLI), so the workflow behaves identically under Claude Code, Codex, or a bare
# terminal. Never force-pushes, never uses --no-verify, never pushes to
# main/master.
set -euo pipefail

branch="$(git rev-parse --abbrev-ref HEAD)"
case "$branch" in
  main|master|HEAD)
    echo "[ship] Refusing to ship from '$branch'. Create a feature branch first." >&2
    exit 1
    ;;
esac

# Refuse a dirty tree — the caller decides whether to commit or stash.
if [ -n "$(git status --porcelain)" ]; then
  echo "[ship] Working tree is dirty. Commit or stash your changes first." >&2
  exit 1
fi

git fetch origin main

if [ -z "$(git log --oneline origin/main..HEAD)" ]; then
  echo "[ship] Nothing to ship: '$branch' has no commits ahead of origin/main." >&2
  exit 1
fi

# Rebase cleanly onto main; surface conflicts rather than auto-resolving.
if ! git pull --rebase origin main; then
  echo "[ship] Rebase onto main hit conflicts. Resolve them, then re-run." >&2
  exit 1
fi

# Push with retry/backoff for transient network failures. Never --force/--no-verify.
attempt=1
delay=2
until git push -u origin "$branch"; do
  if [ "$attempt" -ge 4 ]; then
    echo "[ship] Push failed after $attempt attempts." >&2
    exit 1
  fi
  echo "[ship] Push failed (attempt $attempt); retrying in ${delay}s..." >&2
  sleep "$delay"
  attempt=$((attempt + 1))
  delay=$((delay * 2))
done

echo "[ship] Pushed '$branch'. Open or update its PR with the gh CLI."
