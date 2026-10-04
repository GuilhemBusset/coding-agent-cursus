# Repository conventions

Canonical working conventions for this repo, read by **every** coding agent (Claude Code, Codex,
and any other). `CLAUDE.md` imports this file — do not duplicate conventions there.

## Reproducible tooling

Keep repository-wide setup scripts, dependency manifests and lockfiles, diagnostics, and
installation documentation under `setup/`. The root README should point to `setup/README.md`.

When adding a dependency, skill, MCP server, or other tool, record what it installs and where,
pin dependencies where supported, and provide checked-in setup instructions or a script for
a fresh clone. Do not rely on an agent's global configuration, existing caches, or undocumented
local installations. Keep OS-level installs explicit. Verify setup and report any platform
or environment limitations.

## Platform support

Exercises must work on Linux, macOS and Windows: everything under `sessions/*/exercises/`, and
what students run to set up and hand in that work (the session setup helper, `turn-in`).
Students use their own machines. Exercises are mostly Python run through uv, which keeps this
cheap; prefer Python over shell in them. Everything else (decks, teaching pages, demos, the
HTML tooling, instructor and repo tooling, the implement loop) only needs to work on Linux,
where it is built and presented. See ADR 0010.

## Branching & merging

- `main` is **protected**. Every change lands via a pull request — no direct commits, no direct
  pushes, no force-pushes.
- Work on feature branches named `<type>/<short-description>` (e.g. `feat/login-form`,
  `fix/null-deref`).
- To land a change, open a PR against `main`. The shared `ship` skill automates it (bring the
  branch up to date with `main`, push the feature branch, open/update the PR): run `/ship` in Claude Code or `$ship` in
  Codex; from any other agent, do the equivalent or open the PR by hand.

## Turning in homework

Homework branches are the one branch family that never goes through a PR to `main`. Students
turn in a session's homework with the shared `turn-in` skill: `/turn-in <NN>` in Claude Code,
`$turn-in <NN>` in Codex, or `scripts/turn-in.sh <NN>` from a terminal (for example `01`). It
commits only `sessions/<NN>-*/exercises/` to `homework/s<NN>/<handle>` (`<handle>` is the
student's GitHub login), runs the session's `exercises/turn-in-check.sh` first if there is one
(a failure stops the run), and pushes. Every run adds a commit, so the history keeps every
submission; the `homework-branches` ruleset blocks force-pushes and deletion on these branches.
Students without push access get their fork used instead, plus a compare URL against the course
repo. The repository is public, so homework branches are public too. Never merge a homework
branch, and never rewrite one. See ADR 0009.

## Implementing issues with the loop

To implement an epic or an issue end to end, use the shared `implement` skill (`/implement <n>` in
Claude Code, `$implement <n>` in Codex, or `scripts/implement.sh` from a terminal). A
deterministic engine (`tools/implementation-loop/`, ADR 0008) designs, checks, implements,
reviews and merges each open sub-issue; the vendor that did not write a change reviews it, and
issues close only with evidence. A run never waits for a person (ADR 0011): the engine decides
ambiguities and publishes its decisions in each PR, recovers from failures, or parks an issue
and carries on. The operator only launches and reports: never relay questions, edit a run's
worktrees or issues, commit, merge or tick issue checkboxes by hand while it runs.

## Enforcement

The guarantees are enforced at **agent-independent** layers, so they hold under any agent — or a
bare terminal:

- A GitHub **ruleset** (`setup/pr-only-main.json`, applied once per repo with
  `setup/apply-ruleset.sh`) requires a PR for every change to the default branch, requires the
  `required` CI check to pass (`.github/workflows/ci.yml`, see ADR 0007), and blocks force-pushes
  and branch deletion, with an empty bypass list. This is the hard server-side guarantee.
- `.githooks/pre-commit` blocks commits while `HEAD` is on `main`/`master`; `.githooks/pre-push`
  blocks pushes targeting `refs/heads/main` or `refs/heads/master` (fast local feedback,
  activated once per clone by running `setup/git-hooks.sh`).
- `.github/workflows/pr-only.yml` audits, server-side, that every commit on `main` arrived via a
  merged PR — the backstop that travels with forks, since rulesets are per-repo server state and
  are not inherited until `setup/apply-ruleset.sh` is run there.

There is deliberately **no per-agent guard layer**: no Claude Code or Codex hooks, deny-lists,
or execution-policy rules for `main` (see `docs/adr/0005-drop-per-agent-guard-layer.md`). Every
agent hits the same git hooks and the same server-side rejection, so the rules hold identically
without agent-specific config.

If a hook fires or a push is rejected, fix the underlying issue — do **not** bypass with
`--no-verify` or `--force`.
