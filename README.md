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

Claude Code wires this automatically on session start. Codex does too, once you (a) trust
the project directory at first launch and (b) approve the repo's two hooks via `/hooks` —
Codex trusts hooks per hash, so re-approve them if they change. From any other agent or a
bare terminal, run the script by hand.

## Setup (once per repo, maintainers and fork owners)

Local hooks are convenience; the server-side guarantee is a GitHub ruleset that makes the
default branch PR-only (no direct pushes, no force-pushes, no deletion, no bypass). The
definition is checked in at [`.github/rulesets/pr-only-main.json`](.github/rulesets/pr-only-main.json);
apply it to your repo or fork with an admin-authenticated `gh`:

```sh
./scripts/apply-ruleset.sh
```
