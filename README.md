# coding-agent-cursus

A biweekly five-session cursus on working effectively with coding agents, aimed at
optimization and math PhDs. The session material lives in [`docs/`](docs/).

Working conventions for this repo (branching, merging, enforcement) are in
[`AGENTS.md`](AGENTS.md) — read by every coding agent and by humans alike.

## Setup

Repository-wide installation instructions, dependency manifests, setup scripts, and diagnostics live in
[`setup/`](setup/README.md). Start there after cloning, including when configuring a fork.

## HTML teaching pages

Use `/html-page` in Claude Code or `$html-page` in Codex to create a reading page, deck,
or interactive lab with the shared dark style. Generated HTML opens directly in a browser,
including offline.

See the [shared guide](tools/html-pages/GUIDE.md) for authoring and browser review, and the
[research](tools/html-pages/research.md) for the design and tooling choices.
