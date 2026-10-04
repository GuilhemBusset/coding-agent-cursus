# coding-agent-cursus

A biweekly five-session cursus on working effectively with coding agents, aimed at
optimization and math PhDs. The session material lives in [`docs/`](docs/).

Working conventions for this repo (branching, merging, enforcement) are in
[`AGENTS.md`](AGENTS.md) — read by every coding agent and by humans alike.

## Setup

Repository-wide installation instructions, dependency manifests, setup scripts, and diagnostics live in
[`setup/`](setup/README.md). Start there after cloning, including when configuring a fork.

## Turning in homework

Each session ends with homework, done in that session's `exercises/` folder. Turn it in with
`/turn-in <NN>` in Claude Code or `$turn-in <NN>` in Codex (for example `/turn-in 01`), or with
`scripts/turn-in.sh <NN>` from a terminal. You need git and the GitHub CLI, logged in with
`gh auth login`.

It commits only `sessions/<NN>-*/exercises/` to your own branch `homework/s<NN>/<handle>`
(`<handle>` is your GitHub login) and pushes it; homework never goes to `main` or through a PR.
If the session provides `exercises/turn-in-check.sh`, it runs first and a failure stops the
turn-in. Run it again to resubmit: each run adds a commit, and earlier submissions stay in the
history. Without push access to the course repo, it pushes to your fork and prints a compare URL
for the instructor.

**Homework branches are public**, like the rest of this repository: anyone can read what you
turn in. See [ADR 0009](docs/adr/0009-homework-on-per-student-branches.md).

## Implementing issues

Use `/implement <issue>` in Claude Code or `$implement <issue>` in Codex to have the implement
loop work through an epic or an issue: design, acceptance checks written first, implementation,
a cross-vendor review, and a merge only when every gate is green. See
[`tools/implementation-loop/`](tools/implementation-loop/README.md) and
[ADR 0008](docs/adr/0008-implement-loop.md).

## HTML teaching pages

Use `/html-page` in Claude Code or `$html-page` in Codex to create a reading page, deck,
or interactive lab with the shared dark style. Generated HTML opens directly in a browser,
including offline.

See the [shared guide](tools/html-pages/GUIDE.md) for authoring and browser review, and the
[research](tools/html-pages/research.md) for the design and tooling choices.
