# Contributing

Thanks for contributing to the coding-agent cursus. The working conventions for this
repository — branching, merging, and how `main` is protected — live in one canonical
place: [`AGENTS.md`](AGENTS.md), read by humans and every coding agent alike. This file
is a short pointer; **`AGENTS.md` is the source of truth.**

## First time here

Activate the protected-`main` git hooks once per clone:

```sh
./scripts/setup.sh
```

Claude Code and Codex wire this automatically on session start (via their SessionStart
hooks); from any other agent or a bare terminal, run it by hand.

## Making a change

1. Branch off `main`: `git checkout -b <type>/<short-description>` (e.g. `feat/login-form`,
   `fix/null-deref`, `docs/clarify-readme`, `chore/root-setup`). `main` is protected —
   no direct commits or pushes.
2. Make your change and commit on the feature branch.
3. Land it via a pull request: run `/ship` (in Claude Code or Codex), or open a PR against
   `main` by hand. Do **not** bypass the hooks with `--no-verify` or `--force`.

See [`AGENTS.md`](AGENTS.md) for the full conventions and the agent-independent
enforcement layers (git hooks + CI) that back them.
