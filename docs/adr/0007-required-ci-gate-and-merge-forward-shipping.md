# ADR 0007 — A single required CI check, and merge-forward shipping

- **Status:** Accepted
- **Date:** 2026-10-03
- **Deciders:** Guilhem Busset (instructor / repo owner)
- **Context:** [ADR 0004](0004-server-side-ruleset-and-2026-agent-layer-refresh.md), [ADR 0005](0005-drop-per-agent-guard-layer.md), [ADR 0006](0006-shared-html-authoring-skill.md)

## Context

An implementation loop will soon merge pull requests on its own once every gate passes. Two
gaps in the current setup make that unsafe.

1. **Green was never required.** The ruleset requires a pull request but no passing check, so a
   red PR can still be merged, by a person or an agent. ADR 0004 and ADR 0006 both left CI
   advisory on purpose. The obvious fix, listing every CI job as required, breaks on
   path-filtered workflows: `html-pages.yml` only runs when HTML-related paths change, and a
   required check that never starts leaves every other PR waiting forever.
2. **Re-publishing a PR branch needed a force-push.** `scripts/ship.sh` rebased the branch onto
   `main` on every run. Once a branch is pushed, rebasing rewrites commits the remote already
   has, and the only way to push that is `--force`, which this repo forbids. A resumed or
   updated PR therefore had no legal way forward.

## Decision

1. **One required check, `required`.** A new `.github/workflows/ci.yml` runs on every pull
   request. A `changes` job decides which path-filtered checks apply; `checks.yml` and
   `html-pages.yml` become reusable workflows it calls. A final `required` job runs
   whatever happened and passes only if every applicable check succeeded. Failed, cancelled or
   missing results never count as green, and the HTML checks may be skipped only when no
   HTML-related path changed. `setup/pr-only-main.json` names `required` as its only required
   status check, pinned to GitHub Actions (`integration_id` 15368) so nothing else can post it.
   `strict_required_status_checks_policy` stays off: a branch need not be rebased onto the
   latest `main` before merging. Tools that need that guarantee verify against current `main`
   themselves.
2. **Merge-forward shipping.** `scripts/ship.sh` rebases only a branch that has never been
   pushed. For a published branch it merges `origin/main` into the branch, so every push is a
   fast-forward of the remote branch. If the local branch is missing commits its remote has,
   it stops and asks for a pull instead of overwriting. Both copies of the `ship` skill describe
   this behavior and stay byte-identical. `scripts/test-ship.sh` checks it hermetically
   (throwaway bare remote, this repo's real git hooks) and runs in CI.

Both remain agent-independent, consistent with ADR 0005: the gate is server state plus CI, and
the shipping behavior is a script any agent or person runs the same way.

## Consequences

- Nothing merges into `main` without a green `required` check, whoever merges.
- The ruleset change takes effect only when an administrator re-runs `setup/apply-ruleset.sh`.
  Until then `required` is reported but not enforced.
- Adding a new check means calling it from `ci.yml` and adding it to the `required` job's
  condition; adding it to the ruleset is not needed.
- Published PR branches can now contain merge commits from `main`. Squash merges keep `main`
  history linear regardless.
- Partially supersedes ADR 0004 (point 5: repo checks were advisory) and the corresponding
  sentence of ADR 0006.

## Alternatives considered

1. **List every job as a required check.** Rejected: path-filtered jobs never report on PRs
   that don't match, which blocks those PRs.
2. **Remove the path filters and run the browser checks on every PR.** Rejected: a three-OS
   Playwright matrix on every documentation change costs time for no signal.
3. **Allow force-with-lease for PR branches.** Rejected: the repo forbids force-pushes outright,
   and a merge-forward keeps the reviewed history intact.
