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

Claude Code wires this automatically on session start (via its `SessionStart` hook), so
you only need to run it by hand when working from another agent or a bare terminal.
