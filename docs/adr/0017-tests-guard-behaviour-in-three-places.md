# ADR 0017 — Tests guard behaviour, and live in three places: project, lessons, labs

- **Status:** Accepted
- **Date:** 2026-11-07
- **Deciders:** Guilhem Busset (instructor / repo owner)
- **Context:** [ADR 0001](0001-self-contained-per-session-subfolders.md), [ADR 0012](0012-builder-examiner-loop.md), [ADR 0013](0013-test-tiers-and-selection.md)

## Context

The suites had grown to about 1,500 tests, and most of the browser time went to tests of how pages
look and what they say. Measured locally on 24 cores on 2026-11-07, from `origin/main`:

- **Node and Playwright suites:** 284 tests in 166 s. `world-model-replay` (84 s), `agent-loop`
  (67 s) and `pages` (43 s) led. Each test launched its own browser. Many tests ran at two or
  three viewports, walked every slide for fit, notes and screenshots, or checked print and no-JS
  renderings.
- **Session 1 pytest:** 710 tests in 22 s.
- **Engine tests:** 413 tests in 12 s.
- **Turn-in tests:** 57 tests in 5 s.
- **Page checks:** `check-repo` took 21 s.

Many tests pinned presentation, wording or process rather than behaviour: emphasis, slide copy,
notes wording, word counts, the "spine" visuals, README and ADR sentences, colour tokens, dated
citations, and version-bump checks. Such a test fails when someone edits text, not when something
breaks.

The implement loop had also left 82 examiner probe files (`probe_*.py`, `test_examiner_*`,
`checks/`, `docs/tests/`, `tests/loop_probes/`). Nothing ran them once their issue closed.

The tests were also mixed together:
- `tools/html-pages/tests/` held the page tooling's suites next to the Session 1 deck and lab
  suites.
- Session 1's `tests/` mixed tests of the decks and teaching labs with tests of the exercises
  students run.
- The root `tests/` was mostly probes.

Any change in the session ran all of it.

## Decision

1. **A test guards behaviour someone relies on.** That means:
   - an exercise is solvable, and its checker passes the reference and catches the bugs it is
     meant to catch;
   - a script does its job;
   - a page's controls work, and the numbers it shows come from the real data;
   - a recording is real and sanitised;
   - the tooling does what it documents.

   A test does not pin presentation, wording or process: emphasis, copy, counts, layout at several
   viewports, print, or sentences in a README or ADR. `tools/html-pages/check-page.mjs` is the one
   generic check of every page's layout, accessibility and loading.

   With the owner's approval (ADR 0013 decision 7), the tests that broke this rule were removed or
   cut down on 2026-11-07, and so were the examiner probe files.
2. **Three places, never mixed:**
   - **Project:** the repository's own tooling. A tool's tests live with it
     (`tools/implementation-loop/tests/`, `tools/test-impact/`, and `tools/html-pages/tests/` for
     the page checker and shared components). The tests of the repository's scripts and rules live
     in the root `tests/`: `turn_in/`, `student_setup/`, and `sessions/`, the rules every session
     follows (ADR 0001).
   - **Lessons:** what a session teaches live, its `cursus/` and `index.html`. They live in
     `sessions/<NN>-*/tests/lessons/`: the pytest files, and the browser suites (`*.test.mjs`) for
     its decks and teaching labs.
   - **Labs:** what students run on their own, its `exercises/`, and the editor setup their
     installation of the session carries ([ADR 0016](0016-reproducible-python-editor-setup.md)).
     They live in `sessions/<NN>-*/tests/labs/`.

   A session's `tests/` holds only those two folders; a selector test enforces it. The split
   follows the existing boundary between `cursus/` and `exercises/`.
3. **Selection by part.** `tools/test-impact/impact.toml` gives each part the session paths it
   reads:
   - an `exercises/` change runs the labs;
   - a `cursus/` change runs the lessons;
   - a session file neither claims (its lockfile, its README) runs both;
   - the session's type check runs only when its Python or its pins change.

   CI runs one pytest job per part, and one type-check job per session.
4. **Browser suites run on one browser per file, in parallel.** A suite opens one browser and
   gives each test a page. It drives a representative case end to end, and checks the full data
   in one in-page pass rather than clicking through every case. A suite that loads axe loads it
   once per page.

## Consequences

Measured on the same machine after the change:
- **Node suites:** 122 tests in 19 s.
- **Page checks:** `check-repo` takes about 11 s.
- **Session 1 pytest:** 222 tests in about 6 s.
- **Engine tests:** 389 tests.
- **Turn-in tests:** 35 tests.

What this costs:
- Edits to copy, slides, notes and docs no longer fail tests, so wording is reviewed by people,
  not by tests.
- Some guarantees are now held by one generic check instead of a per-page one. Per-viewport layout
  of each page is checked only by `check-page.mjs`, at its viewports. Component accessibility at
  desktop width rests on axe in `check-page.mjs`. The predict cards' answer keys rest on the
  component suite.
- The no-JS and print fallbacks of the teaching labs are no longer compared with what the page
  computes. The instructor runs them with JavaScript.
- The implement loop still adopts examiner probes into the tree. They are evidence for their issue
  and nothing runs them afterwards, so remove them once the issue closes, or move a real check into
  the part it belongs to.
