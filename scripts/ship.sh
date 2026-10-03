#!/usr/bin/env bash
# Portable, agent-independent core of the ship skill (/ship in Claude Code,
# $ship in Codex).
#
# Asserts we are on a feature branch, brings it up to date with main, and
# pushes it with retry/backoff. A branch that has never been pushed is rebased
# onto main (clean, linear history). A branch that is already published gets
# main merged into it instead, so every later push is a fast-forward of the
# remote branch and never needs --force. PR creation is delegated to the
# calling agent (via the `gh` CLI), so the workflow behaves identically under
# Claude Code, Codex, or a bare terminal. Never force-pushes, never uses
# --no-verify, never pushes to main/master.
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

# Bring the branch up to date with main; surface conflicts rather than
# auto-resolving. Rebasing a published branch would rewrite history the remote
# already has, and the only way to push that is --force, so published branches
# merge main in instead.
if git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
  git fetch origin "$branch"
  if ! git merge-base --is-ancestor "origin/$branch" HEAD; then
    echo "[ship] '$branch' is missing commits that origin/$branch has. Pull them first (git pull --no-rebase origin $branch); never force-push." >&2
    exit 1
  fi
  if ! git merge-base --is-ancestor origin/main HEAD; then
    if ! git merge --no-edit origin/main; then
      echo "[ship] Merging main into '$branch' hit conflicts. Resolve them, commit, then re-run." >&2
      exit 1
    fi
  fi
else
  if ! git rebase origin/main; then
    echo "[ship] Rebase onto main hit conflicts. Resolve them (or git rebase --abort), then re-run." >&2
    exit 1
  fi
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
