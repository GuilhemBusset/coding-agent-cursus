# Repository conventions

## Branching & merging

- `main` is **protected**. Every change lands via a pull request — no direct commits, no direct pushes, no force-pushes.
- Work on feature branches named `<type>/<short-description>` (e.g. `feat/login-form`, `fix/null-deref`).
- To merge: run `/ship` in Claude Code. It rebases onto `main`, pushes, and opens/updates a PR.

## Enforcement

- `.githooks/pre-commit` blocks commits while `HEAD` is on `main`/`master`.
- `.githooks/pre-push` blocks pushes targeting `refs/heads/main` or `refs/heads/master`.
- The Claude Code `SessionStart` hook wires `core.hooksPath` to `.githooks` automatically.
- A `PreToolUse` hook (`.claude/hooks/guard-main.sh`) refuses any Bash call that would commit on or push to main/master.
- `.claude/settings.json` denies the corresponding `Bash(git push ...)` patterns as a belt-and-braces safety net.

If a hook fires, fix the underlying issue — do **not** bypass with `--no-verify` or `--force`.

## Setup (only needed outside a Claude Code session)

```sh
git config core.hooksPath .githooks
chmod +x .githooks/*
```
