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

No agent runs this for you, whether you use Claude Code, Codex, or a bare terminal. Run it
by hand; it is safe to re-run.

If you administer this repo (or your own fork), also apply the server-side PR-only
ruleset once: `./scripts/apply-ruleset.sh` (see [`AGENTS.md`](AGENTS.md) → Enforcement).

## Making a change

1. Branch off `main`: `git checkout -b <type>/<short-description>` (e.g. `feat/login-form`,
   `fix/null-deref`, `docs/clarify-readme`, `chore/root-setup`). `main` is protected —
   no direct commits or pushes.
2. Make your change and commit on the feature branch.
3. Land it via a pull request: run `/ship` (Claude Code) or `$ship` (Codex), or open a PR
   against `main` by hand. Do **not** bypass the hooks with `--no-verify` or `--force`.

See [`AGENTS.md`](AGENTS.md) for the full conventions and the agent-independent
enforcement layers (ruleset + git hooks + CI audit) that back them.
