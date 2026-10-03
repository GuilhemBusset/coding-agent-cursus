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
  activated once per clone by running `scripts/setup.sh`).
- `.github/workflows/pr-only.yml` audits, server-side, that every commit on `main` arrived via a
  merged PR — the backstop that travels with forks, since rulesets are per-repo server state and
  are not inherited until `scripts/apply-ruleset.sh` is run there.

There is deliberately **no per-agent guard layer**: no Claude Code or Codex hooks, deny-lists,
or execution-policy rules for `main` (see `docs/adr/0005-drop-per-agent-guard-layer.md`). Every
agent hits the same git hooks and the same server-side rejection, so the rules hold identically
without agent-specific config.

If a hook fires or a push is rejected, fix the underlying issue — do **not** bypass with
`--no-verify` or `--force`.
