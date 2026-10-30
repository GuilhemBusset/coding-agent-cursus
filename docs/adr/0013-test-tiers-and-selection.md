# ADR 0013 — Run what a change can affect on pull requests, everything on main and nightly

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** Guilhem Busset (instructor / repo owner)
- **Context:** [ADR 0007](0007-required-ci-gate-and-merge-forward-shipping.md), [ADR 0010](0010-platform-support.md), [ADR 0012](0012-builder-examiner-loop.md)

## Context

A one-deck pull request cost about 12 minutes of CI and several minutes of local checks.
Agents reran the full suites many times per task. Measured on 2026-10-28 and 2026-10-29:

- **CI.** The `required` gate waited for every job: the HTML job (734 s median, its Node suites
  and page checks back to back), session pytest (286 s) and repo checks (284 s, of which 265 s
  were the implement-loop engine tests). Every pull request ran all of them, whatever it touched.
  Queue time (about 2 s) and setup (about 25 s) were not where the time went.
- **Locally.** On a 24-core machine: Node suites 123 s, `check-repo` 211 s, session pytest
  221 s, engine tests 119 s. Most of it was serial work on idle cores, and fixed sleeps: 47 s of
  server shutdown polling in the pre-work tests, and about 55 s of `waitForTimeout` in
  `check-page.mjs`.

Most pull requests touch one area. Deck pull requests change a deck and its suite; engine
pull requests change only `tools/implementation-loop/`; exercise pull requests change one
session's `exercises/`. The tests' inputs are narrow too: outside their session folder, session
tests read only `scripts/turn-in.sh` and `.githooks/`, and the engine tests read only their own
folder, the shipping scripts and hooks, and a handful of named files. A user-owned repository has
no merge queue, so a full run can only follow a merge, never gate it.

## Decision

1. **Two tiers.** The `required` check on a pull request runs the checks the pull request's
   changed paths can affect. Every push to `main`, a nightly schedule and a manual dispatch run
   everything on `ubuntu-latest`; a failure there opens or updates one issue. The nightly run is
   also the canary for runner and toolchain drift, such as the Git 2.56 change that broke the
   pre-work tests before any pull request showed it.
2. **One map, used locally and in CI.** `tools/test-impact/impact.toml` maps paths to checks:
   the engine tests, each session's pytest suite, each Node suite, `check-page.mjs` per teaching
   page, the turn-in tests, `test-ship.sh` and the static repo checks. `tools/test-impact/impact.py`
   applies it, standard library only. `scripts/check-changed.sh` runs the selection locally (the
   change since the merge base with `origin/main`, including uncommitted and untracked files).
   ci.yml's `changes` job computes the same selection from the pull request's `BASE...HEAD`.
3. **The map errs wide.**
   - A changed path that no rule matches runs everything.
   - A change to a workflow, the selector, the map or the locked npm packages runs everything.
   - A Node suite with no map entry runs on every change.
   - A deleted or renamed file counts under its old path.
   - A page is checked when it changes, when a file it loads changes, or when a file it links to
     is deleted or renamed.
   - A session's suite runs on any change in its folder.

   The selector's tests (`tools/test-impact/test_impact.py`) pin these rules.
4. **The gate keeps ADR 0007's semantics.** `changes` must succeed. Each filtered job counts as
   green only if it succeeded, or if it was skipped and `changes` said it did not apply. A
   missing, cancelled or failed result is never green. The ruleset still requires only `required`.
5. **Parallel by default.**
   - Session pytest runs under pytest-xdist, from a non-default `parallel` dependency group, so
     students' `uv sync` is unchanged.
   - The engine tests run in their own job under pytest-xdist.
   - `check-repo` checks several pages at once.
   - The HTML job is three jobs side by side: two Node-suite shards and the pages.
6. **Fixed waits become condition waits** where the wait stood in for a condition. The pre-work
   test server polls for shutdown every 10 ms, not 0.5 s. `check-page.mjs` waits for fonts and
   two animation frames, or for the target slide.
7. **Duplicates are removed only with the owner's approval,** naming the test that still holds
   each guarantee. Approved on 2026-10-29: the duplicate Node suites and tests, the session
   examiner duplicates, and `check-page.mjs`'s per-slide axe run at the desktop viewport (the
   laptop and mobile runs remain).

## Consequences

- A pull request whose map entry is too narrow can merge green and break `main`. The push-to-main
  run catches that within one run, and a fix-forward or revert goes through a pull request as
  usual (ADR 0012 decision 7). When a test starts reading a new file, its author adds that file to
  the map.
- Deck and exercise pull requests no longer wait for the engine tests, and engine pull requests no
  longer wait for the browser checks. When everything runs, the jobs run side by side instead of
  one after another.
- Every agent and person has one fast command before pushing, `scripts/check-changed.sh`, and
  narrower ones while iterating (AGENTS.md, `setup/README.md`).
- Session suites still run in `required` on every pull request that touches their session (ADR
  0010, ADR 0012); a pull request that touches no session no longer runs them.
- More jobs and minutes per full run. The repository is public, so GitHub-hosted runners cost
  nothing; no larger runner is used.
- Scheduled workflows stop after 60 days without repository activity. The push-to-main run does
  not depend on the schedule.

## Alternatives considered

1. **Keep running everything on every pull request, only faster.** Parallelism alone brings the
   gate to about 4 minutes, but an engine change still waits for browsers and a deck change for
   the engine. Rejected as the only lever, kept as the full-run tier.
2. **A merge queue running the full suite before merge.** Not available on a user-owned
   repository.
3. **Larger runners.** They cost money, and the free 4-vCPU runners reach the target.
4. **Pinning the runner image or toolchain.** `ubuntu-24.04` images still update Git weekly; the
   nightly canary warns before pull requests fail.
5. **Ordering Node suites longest first.** Measured: no gain (198.6 s against 199.0 s on 4
   cores), because one suite, world-model, is the critical path.
6. **Dropping screenshots in CI.** They are the review artefact; identical paged screenshots
   are copied instead of captured twice.
