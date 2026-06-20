---
name: ship
description: Clean-merge the current branch to main via PR. Invoke explicitly with /ship when the user wants to land a finished feature branch.
disable-model-invocation: true
allowed-tools: Bash, Read
---

# /ship — open and merge a PR to `main`

You are shipping the current branch. Goal: get the work merged into `main` via a clean PR. Never push directly to `main`.

The deterministic git mechanics (assert-not-on-main, dirty-tree check, rebase onto `main`, push with retry) live in `scripts/ship.sh`, the single agent-independent source of truth, so this workflow is identical under Claude Code, Codex, or a bare terminal. The twin Codex skill at `.agents/skills/ship/SKILL.md` drives the same script. This skill drives that script, then opens/updates the PR with the agent-independent `gh` CLI (no MCP server required).

## Preflight (do all in parallel where possible)

1. `git rev-parse --abbrev-ref HEAD` — confirm we are NOT on `main`/`master`. If we are, STOP and tell the user to create a feature branch.
2. `git status --porcelain` — if dirty, ask the user whether to commit the remaining changes or stash them. Do not silently commit unrelated work. (`scripts/ship.sh` will also refuse a dirty tree.)
3. `git fetch origin main` then `git log --oneline origin/main..HEAD` — confirm there are commits to ship. If zero, STOP and report "nothing to ship".
4. `git log --oneline -20` and `git diff origin/main...HEAD --stat` — read the actual changes so the PR description reflects reality.

## Rebase and push

5. Run `scripts/ship.sh`. It rebases the current branch onto `main` and pushes it with retry/backoff (never `--force`, never `--no-verify`). If it reports a rebase conflict, STOP and surface it — do NOT auto-resolve unless instructed.

## Open or update the PR (via `gh`)

6. Confirm `gh` is authenticated (`gh auth status`); if not, tell the user to run `gh auth login`.
7. Check for an existing open PR for this branch (`gh pr view --json url,state` — a non-zero exit means none exists). Write the PR body to a temp file so multi-line Markdown is preserved, then:
   - If one exists, update it: `gh pr edit --body-file <file>`.
   - If none, create it: `gh pr create --base main --head <current-branch> --title "<title>" --body-file <file>`.
   - **Title:** concise (<70 chars), imperative, summarizing the change.
   - **Body:** `## Summary` (1-3 bullets describing the *why*) and `## Test plan` (checklist of how the change was validated).

## Land it

8. Report the PR URL (`gh pr view --json url --jq .url`). Then ask whether to:
   - **enable auto-merge** (squash) once checks pass — `gh pr merge --squash --auto`, OR
   - **merge now** if checks are already green — `gh pr merge --squash`, OR
   - **leave it open** for review.

Only proceed with merge/auto-merge after explicit user confirmation.

## Hard rules

- Never run `git push origin main`, `git push --force`, or `git commit --no-verify`.
- Never bypass the `.githooks` checks.
- Never close, force-update, or rewrite the history of a PR branch without asking.
- If anything is ambiguous (dirty tree, divergent history, failing checks), ask before acting.
