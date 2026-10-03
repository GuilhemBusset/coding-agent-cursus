#!/usr/bin/env bash
# One-command, idempotent application of the repo's server-side PR-only ruleset.
#
# Rulesets are per-repo server state: they are NOT inherited by forks or new
# repos, so the definition is checked in (setup/pr-only-main.json)
# and this script applies it. Run it once per repo (original or fork) with a
# gh CLI authenticated as a repo admin:
#
#   ./setup/apply-ruleset.sh
#
# Until it has run, the CI audit (.github/workflows/pr-only.yml) and the local
# git hooks remain the backstop. Requires: gh (authenticated), jq.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

ruleset_file="setup/pr-only-main.json"
name="$(jq -r .name "$ruleset_file")"
repo="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"

existing_id="$(gh api "repos/$repo/rulesets" \
  --jq ".[] | select(.name == \"$name\") | .id" | head -n1)"

if [ -n "$existing_id" ]; then
  gh api --method PUT "repos/$repo/rulesets/$existing_id" \
    --input "$ruleset_file" >/dev/null
  echo "[ruleset] Updated ruleset '$name' (id $existing_id) on $repo."
else
  gh api --method POST "repos/$repo/rulesets" \
    --input "$ruleset_file" >/dev/null
  echo "[ruleset] Created ruleset '$name' on $repo."
fi
