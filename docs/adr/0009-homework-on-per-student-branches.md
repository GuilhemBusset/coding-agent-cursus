# ADR 0009 — Homework is turned in on per-student branches, via a shared `turn-in` skill

- **Status:** Accepted
- **Date:** 2026-10-04
- **Deciders:** Guilhem Busset (instructor / repo owner)
- **Context:** [ADR 0001](0001-self-contained-per-session-subfolders.md), [ADR 0002](0002-agent-agnostic-claude-code-and-codex.md), [ADR 0003](0003-ship-as-shared-skill-and-codex-convenience-layer.md), [ADR 0004](0004-server-side-ruleset-and-2026-agent-layer-refresh.md), [ADR 0007](0007-required-ci-gate-and-merge-forward-shipping.md)

## Context

Every session ends with homework done in the session's `exercises/` folder (ADR 0001). Students
need one way to hand it in that works the same all term, under Claude Code or Codex (students
have one of the two, not necessarily both — ADR 0002), and that never touches `main`, which only
changes through pull requests (ADR 0004, ADR 0007). Homework is not a change to the course: it
must not open a PR, must not be merged, and the instructor must be able to see every submission,
not only the last one.

## Decision

1. **One branch per student and session: `homework/s<NN>/<handle>`.** `<handle>` is the
   student's GitHub login, read with `gh api user`. Homework branches never merge to `main`;
   they are the one branch family that does not go through a PR.

2. **The `ship` pattern from ADR 0003: a thin skill over an agent-independent script.**
   `scripts/turn-in.sh <NN>` holds all the mechanics. `.claude/skills/turn-in/SKILL.md` and
   `.agents/skills/turn-in/SKILL.md` are byte-identical thin wrappers (CI diffs them), invoked
   explicitly only as `/turn-in <NN>` or `$turn-in <NN>`, with the same flags as `ship`
   (`disable-model-invocation: true`; `policy.allow_implicit_invocation: false` in
   `.agents/skills/turn-in/agents/openai.yaml`). A student without either agent runs the script
   from a terminal.

3. **Only the session's `exercises/` folder is ever submitted.** The script stages and commits
   with that folder as its pathspec, so other changes, staged or not, stay in the working tree.
   A new homework branch starts from the course repo's default branch (not from whatever `HEAD`
   is), and the script refuses if `HEAD` has commits that are not on it or if the branch would
   change anything outside `exercises/` relative to it. The push refspec is fixed to
   `HEAD:refs/heads/homework/s<NN>/<handle>` after strict validation of `<NN>` and the handle,
   so it cannot target `main`.

4. **One commit per run; history only grows.** Every successful run adds exactly one commit
   (empty if nothing changed), and the remote branch only fast-forwards. The script never uses
   `--force` or `--no-verify`, and never stashes, resets or rebases: a divergent branch or a
   switch that would overwrite uncommitted work is a refusal with an explanation.

5. **An optional per-session gate.** If `sessions/<NN>-*/exercises/turn-in-check.sh` exists,
   the script runs it from the session folder; a non-zero exit stops the run before any commit
   or push. The check belongs to the session (ADR 0001); the script is cursus-wide.

6. **Server-side protection: `setup/homework-branches.json`.** A second ruleset, applied with
   `setup/pr-only-main.json` by `setup/apply-ruleset.sh`, blocks force-pushes
   (`non_fast_forward`) and deletion on every homework branch, with no bypass actors. It targets
   `refs/heads/homework/**/*`: GitHub matches ruleset refs with `fnmatch` and `FNM_PATHNAME`, so
   `*` never crosses a `/` and `refs/heads/homework/**` alone does not reach the nested
   `homework/s01/<handle>`.

7. **Fork fallback.** When `origin` is itself a fork, the course repo is its parent and the
   student pushes to `origin`. When `origin` is the course repo and the student lacks write
   access, the script runs `gh repo fork --clone=false`, identifies the student's fork through
   the forks API (it may be named `<repo>-1`; a named `fork` remote is never trusted), and pushes
   there by explicit URL. In both cases it prints a compare URL against the course repo's
   default branch. A generic push failure is retried but never switches destination.

## Consequences

**Positive**
- One command, the same in both agents and in a terminal, for the whole term.
- Every submission is kept: the instructor reads the branch history, and the ruleset makes it
  impossible to rewrite or delete on the course repo.
- `main` stays PR-only; homework never appears in its history or in the PR queue.

**Negative / costs (accepted)**
- **Homework branches are public.** The course repository is public, so every
  `homework/s<NN>/<handle>` branch (and every fork) is visible to anyone. The instructor
  confirms this on the PR that introduces the skill; the `Turning in homework` sections of
  `README.md` and `AGENTS.md` say so, and the student pre-work page should too.
- Fork branches live in the student's repository, outside the course ruleset: the student can
  rewrite or delete them there. The compare URL is the instructor's view of the submission.
- Students need an authenticated `gh` in addition to git.
- The skill prose exists twice, as for `ship` (ADR 0003); CI diffs the two copies.

## Alternatives considered

1. **Homework as PRs to `main`.** Rejected: it mixes submissions with course changes, invites
   accidental merges, and a PR shows the latest state rather than every submission.
2. **`homework/**` as the ruleset pattern.** Rejected: with `FNM_PATHNAME` it does not match
   nested names such as `homework/s01/<handle>`.
3. **A separate private submissions repo.** Rejected for now: one more repo to set up and grant
   access to per student; revisit if public homework becomes a problem.
4. **Amending one commit per submission.** Rejected: it needs a force-push and loses history.

## How this stays true

- The mechanics stay single-sourced in `scripts/turn-in.sh`; both skill copies only wrap it.
- CI runs `tests/turn_in/` (the script in throwaway repos with a fake `gh`, the rulesets, the
  skill copies and these docs) and parses every shell file with `bash -n`.
- `setup/turn-in-owner-checks.md` is the owner's live check after merge and after
  `setup/apply-ruleset.sh`: both agents push, a second run adds a commit, a force-push is
  rejected by the `homework-branches` ruleset.
