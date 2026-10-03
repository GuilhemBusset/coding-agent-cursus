# coding-agent-cursus

A biweekly five-session cursus on working effectively with coding agents, aimed at
optimization and math PhDs. The session material lives in [`docs/`](docs/).

Working conventions for this repo (branching, merging, enforcement) are in
[`AGENTS.md`](AGENTS.md) — read by every coding agent and by humans alike.

## Setup (once per clone)

`main` is protected by git hooks under `.githooks/`. Those hooks are inert until the
hooks path is activated, so run this once per clone:

```sh
./scripts/setup.sh
```

No agent runs this for you, whether you use Claude Code, Codex, or a bare terminal. Run it
by hand; it is safe to re-run.

## Setup (once per repo, maintainers and fork owners)

Local hooks are convenience; the server-side guarantee is a GitHub ruleset that makes the
default branch PR-only (no direct pushes, no force-pushes, no deletion, no bypass). The
definition is checked in at [`.github/rulesets/pr-only-main.json`](.github/rulesets/pr-only-main.json);
apply it to your repo or fork with an admin-authenticated `gh`:

```sh
./scripts/apply-ruleset.sh
```
