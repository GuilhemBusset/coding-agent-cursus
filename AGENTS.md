# Repository conventions

Canonical working conventions for this repo, read by **every** coding agent (Claude Code, Codex,
and any other). `CLAUDE.md` imports this file — do not duplicate conventions there.

## Branching & merging

- `main` is **protected**. Every change lands via a pull request — no direct commits, no direct
  pushes, no force-pushes.
- Work on feature branches named `<type>/<short-description>` (e.g. `feat/login-form`,
  `fix/null-deref`).
- To land a change, open a PR against `main`. The shared `ship` skill automates it (rebase onto
  `main`, push the feature branch, open/update the PR): run `/ship` in Claude Code or `$ship` in
  Codex; from any other agent, do the equivalent or open the PR by hand.

## Enforcement

The guarantees are enforced at **agent-independent** layers, so they hold under any agent — or a
bare terminal:

- A GitHub **ruleset** (`.github/rulesets/pr-only-main.json`, applied once per repo with
  `scripts/apply-ruleset.sh`) requires a PR for every change to the default branch and blocks
  force-pushes and branch deletion, with an empty bypass list. This is the hard server-side
  guarantee.
- `.githooks/pre-commit` blocks commits while `HEAD` is on `main`/`master`; `.githooks/pre-push`
  blocks pushes targeting `refs/heads/main` or `refs/heads/master` (fast local feedback,
  activated by `scripts/setup.sh`).
- `.github/workflows/pr-only.yml` audits, server-side, that every commit on `main` arrived via a
  merged PR — the backstop that travels with forks, since rulesets are per-repo server state and
  are not inherited until `scripts/apply-ruleset.sh` is run there.

Each agent then layers a thin **convenience** wrapper over the same rules — Claude Code
(`.claude/settings.json`) and Codex (`.codex/config.toml`) both wire a `PreToolUse` guard that
runs the shared `scripts/guard-main.sh`, plus a SessionStart hook that activates the git hooks
via `scripts/setup.sh`. Claude Code adds a `settings.json` deny-list; Codex adds declarative
execution-policy rules (`.codex/rules/protected-main.rules`). Codex loads the project layer only
after you trust the project, and each hook must be trusted once via `/hooks` (trust is per hook
hash — re-trust after any hook change). These give a fast in-loop block. They accelerate
feedback; they are never the only thing standing between you and a bad push.

If a hook fires, fix the underlying issue — do **not** bypass with `--no-verify` or `--force`.
