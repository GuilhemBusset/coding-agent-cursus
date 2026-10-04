#!/usr/bin/env bash
# One-command, idempotent application of the repo's server-side rulesets:
#
#   setup/pr-only-main.json       PR-only changes to the default branch, required CI
#                                 check, no force-push, no deletion.
#   setup/homework-branches.json  No force-push and no deletion on every homework branch
#                                 (refs/heads/homework/**/*, nested names included), see
#                                 docs/adr/0009-homework-on-per-student-branches.md.
#
# Rulesets are per-repo server state: they are NOT inherited by forks or new
# repos, so the definitions are checked in and this script applies them, each
# matched by name (created if missing, updated otherwise). Run it once per repo
# (original or fork) with a gh CLI authenticated as a repo admin:
#
#   ./setup/apply-ruleset.sh
#
# Until it has run, the CI audit (.github/workflows/pr-only.yml) and the local
# git hooks remain the backstop. Fails if either ruleset cannot be applied.
# Requires: gh (authenticated), jq.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

repo="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"

for ruleset_file in setup/pr-only-main.json setup/homework-branches.json; do
  name="$(jq -r .name "$ruleset_file")"

  existing_ids="$(gh api --paginate "repos/$repo/rulesets" \
    --jq ".[] | select(.name == \"$name\") | .id")"
  existing_id="${existing_ids%%$'\n'*}"

  if [ -n "$existing_id" ]; then
    gh api --method PUT "repos/$repo/rulesets/$existing_id" \
      --input "$ruleset_file" >/dev/null
    echo "[ruleset] Updated ruleset '$name' (id $existing_id) on $repo."
  else
    gh api --method POST "repos/$repo/rulesets" \
      --input "$ruleset_file" >/dev/null
    echo "[ruleset] Created ruleset '$name' on $repo."
  fi
done
