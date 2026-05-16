---
description: Clean-merge the current branch to main via PR.
allowed-tools: Bash, Read, Edit, mcp__github__create_pull_request, mcp__github__list_pull_requests, mcp__github__update_pull_request, mcp__github__enable_pr_auto_merge, mcp__github__merge_pull_request, mcp__github__pull_request_read
---

# /ship — open and merge a PR to `main`

You are shipping the current branch. Goal: get the work merged into `main` via a clean PR. Never push directly to `main`.

## Preflight (do all in parallel where possible)

1. `git rev-parse --abbrev-ref HEAD` — confirm we are NOT on `main`/`master`. If we are, STOP and tell the user to create a feature branch.
2. `git status --porcelain` — if dirty, ask the user whether to commit the remaining changes or stash them. Do not silently commit unrelated work.
3. `git fetch origin main` then `git log --oneline origin/main..HEAD` — confirm there are commits to ship. If zero, STOP and report "nothing to ship".
4. `git log --oneline -20` and `git diff origin/main...HEAD --stat` — read the actual changes so the PR description reflects reality.

## Rebase cleanly onto main

5. `git pull --rebase origin main`. If conflicts appear, stop and surface them — do NOT auto-resolve unless instructed.

## Push

6. `git push -u origin <current-branch>`. Retry on transient network failures up to 4 times with exponential backoff (2s, 4s, 8s, 16s). Never use `--force` or `--no-verify`.

## Open or update the PR

7. Check if an open PR already exists for this branch (`mcp__github__list_pull_requests`). If yes, update its body with the latest summary; if no, create one with `mcp__github__create_pull_request`:
   - **Base:** `main`
   - **Head:** the current branch
   - **Title:** concise (<70 chars), imperative, summarizing the change
   - **Body:** `## Summary` (1-3 bullets describing the *why*) and `## Test plan` (checklist of how the change was validated)

## Land it

8. Report the PR URL to the user. Then ask whether to:
   - **enable auto-merge** (squash) once checks pass — use `mcp__github__enable_pr_auto_merge`, OR
   - **merge now** if checks are already green — use `mcp__github__merge_pull_request` with `merge_method: "squash"`, OR
   - **leave it open** for review.

Only proceed with merge/auto-merge after explicit user confirmation.

## Hard rules

- Never run `git push origin main`, `git push --force`, or `git commit --no-verify`.
- Never bypass the `.githooks` checks.
- Never close, force-update, or rewrite the history of a PR branch without asking.
- If anything is ambiguous (dirty tree, divergent history, failing checks), ask before acting.
