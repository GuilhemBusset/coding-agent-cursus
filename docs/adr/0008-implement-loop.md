# ADR 0008 — The implement loop: a deterministic engine, agents as workers

- **Status:** Accepted
- **Date:** 2026-10-03
- **Deciders:** Guilhem Busset (instructor / repo owner)
- **Context:** [ADR 0002](0002-agent-agnostic-claude-code-and-codex.md), [ADR 0003](0003-ship-as-shared-skill-and-codex-convenience-layer.md), [ADR 0005](0005-drop-per-agent-guard-layer.md), [ADR 0007](0007-required-ci-gate-and-merge-forward-shipping.md)

## Context

Session content is planned as GitHub epics: tracking issues per part, work items as native
sub-issues, native blocked-by links, and checkbox Deliverables and Acceptance criteria. We want
to hand an epic (or one issue) to agents and get merged, verified work back, with a review by a
different vendor than the one that wrote the code, and without trusting any agent's own
"done". The loop must run identically from Claude Code, from Codex, or from a terminal.

The design was converged over two rounds with Codex and an industry review (Claude Code dynamic
workflows, Codex `/goal`, Copilot, Cursor, Devin, Kiro, Spec Kit; research on multi-agent
debate, cross-model review and reward hacking such as ImpossibleBench).

## Decision

1. **A deterministic engine owns the loop.** `tools/implementation-loop/` (Python, standard
   library) builds the graph from GitHub, keeps resumable state, schedules work, runs the
   checks, and is the only code that commits, pushes, comments or merges. Agents are fresh
   headless processes behind one interface. Native features (Claude Code workflows, Codex
   subagents, `/goal`) may accelerate a phase later but never decide that work is done.
2. **Roles by vendor.** The vendor that launched the run (the operator) proposes, judges and
   implements; the other vendor also proposes, audits the criteria, writes the acceptance checks
   and reviews. Swapping the operator swaps every role.
3. **Done means evidence.** Every ledger item maps to a command check, a reviewer-judged
   artifact, or a task for a person. Checks are written before code, committed first, locked by
   hash (with the test configuration pytest would load) and run by the engine's own verifier;
   all expected tests must run and none may skip. A reproduced review defect blocks whatever its
   priority. Evidence is recorded per commit and posted as a PR comment; CI artifacts may expire.
4. **Landing is serialized and exact.** One PR per issue (`Refs #N`, never `Closes`), pushed
   without force (ADR 0007), merged only when the `required` check is green on the exact
   reviewed head and with that head SHA as a precondition. A changed head goes back to verify
   and review. Merging is gated, not manual: the user's confirmation at launch is the merge
   approval the `ship` skill asks for.
5. **Issues close on evidence, not on merge.** After merging, the engine re-verifies on `main`,
   ticks the ledger with evidence links, and closes the issue only when every item is proven.
   Items only a person can prove keep the issue open but no longer block dependents.
6. **Caps, not budgets.** 2 design rounds, 3 implement-verify attempts, 2 fix rounds, a stuck
   detector and a `STOP` file. Hitting a cap ends that issue in `needs_human`; independent work
   carries on. There is no token or dollar cap, by choice; cost is logged.
7. **State outside the worktrees.** Run state lives under the git common dir; worktrees live in
   a sibling `<repo>.loop/` directory. A repo-wide claim serializes merges across runs.

8. **Agents are workers without credentials.** Each call is a fresh headless `claude -p` or
   `codex exec` process with per-role permissions (read-only for explorers, designers and
   reviewers). Per-tool deny rules turned out to be prefix matches an agent can sidestep, so
   they are a convenience only: agents run with GitHub credentials removed from their
   environment, any commit an agent makes is undone and recommitted by the engine, and every
   prompt and answer is recorded for audit.
9. **One skill, both harnesses.** `implement` is a byte-identical `SKILL.md` pair (ADR 0003) that
   runs the preflight, shows the plan, asks the user to confirm self-merging, launches
   `scripts/implement.sh run` in the background and reports progress. A CI step
   (`scripts/check-loop-guard.sh`) also fails a PR if a later commit changes acceptance checks
   the loop locked.

All guards stay agent-independent (ADR 0005): the engine, git hooks, the ruleset and CI.

## Consequences

- An epic can be run, stopped, edited and resumed; a changed issue body invalidates its design.
- The engine core is testable without models: the suite drives real git, `ship.sh`, the
  verifier and squash merges against a throwaway remote, with scripted agents.
- Wrongly declared file sets cost parallelism, not correctness: overlapping issues wait.
- A run cannot finish work that needs a person (rehearsals, other accounts, live recordings);
  it lists those tasks on the epic instead of fabricating them.

## Alternatives considered

1. **Claude Code's Workflow tool as the engine.** Rejected as the core: Claude Code only, resume
   within one session, and no place for a Codex-driven run. Kept as a possible accelerator.
2. **Codex-native orchestration (`/goal`, subagents).** Rejected for the same reason in reverse,
   and because a model judging its own completion is the failure mode we are guarding against.
3. **One integration branch and one PR per epic.** Rejected: one huge review, and issues would
   only close at the very end. Per-issue PRs keep review small and dependents unblocked.
4. **Debate until consensus in design.** Rejected: research shows debate rarely beats
   independent proposals plus a judge, and sycophancy grows with rounds; we cap at two.
