# ADR 0010 — Exercises are cross-platform; everything else only needs Linux

- **Status:** Accepted
- **Date:** 2026-10-04
- **Deciders:** Guilhem Busset (instructor / repo owner)
- **Context:** [ADR 0001](0001-self-contained-per-session-subfolders.md), [ADR 0006](0006-shared-html-authoring-skill.md), [ADR 0007](0007-required-ci-gate-and-merge-forward-shipping.md), [ADR 0009](0009-homework-on-per-student-branches.md)

## Context

Students do the exercises on their own machines, under Linux, macOS or Windows. The instructor
builds and presents the course material on Linux. Until now CI checked the HTML page tooling on
all three platforms (`html-pages.yml`), so every teaching page paid for Windows and macOS quirks
on platforms nobody presents from.

PR #61 showed the cost. A Windows checkout converted `tools/html-pages/assets/theme.css` to CRLF
line endings, so its hash no longer matched the snapshot hash stored in the sample page. A change
that passed on Linux and macOS could not merge.

## Decision

1. **Exercises are cross-platform.** Everything under `sessions/*/exercises/`, and what students
   run to set up and hand in that work (the session setup helper, `turn-in`), must work on Linux,
   macOS and Windows. Exercises are mostly Python run through uv, which keeps this cheap; prefer
   Python over shell in them.
2. **Everything else only needs Linux.** Decks, teaching pages, demos, the HTML tooling,
   instructor and repo tooling, and the implement loop are built, checked and presented on
   Linux. CI checks the HTML tooling on `ubuntu-latest` only.

## Consequences

- The HTML tooling check is one Linux job instead of three, and Windows line-ending and path
  quirks no longer block teaching material.
- Pages stay static files opened over `file://`. A student can still open one in any browser,
  but only Linux Chromium is checked.
- CI does not enforce exercise portability yet: no workflow runs the sessions' tests. A
  cross-platform job for the sessions' exercises is the natural follow-up.
- The shell scripts students run (the setup helper, `turn-in`) stay Bash, which Windows
  students run in Git Bash.
