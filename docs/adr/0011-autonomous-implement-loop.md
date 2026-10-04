# ADR 0011 — The implement loop runs to the end without waiting for a person

- **Status:** Accepted
- **Date:** 2026-10-04
- **Deciders:** Guilhem Busset (instructor / repo owner)
- **Context:** [ADR 0008](0008-implement-loop.md), [ADR 0005](0005-drop-per-agent-guard-layer.md), [ADR 0007](0007-required-ci-gate-and-merge-forward-shipping.md), [ADR 0010](0010-platform-support.md)
- **Supersedes:** ADR 0008 decisions 5 and 6, and its consequence "a changed issue body invalidates its design"

## Context

The loop's first two real runs, on 2026-10-04 (`/implement 20`, then epic #11), merged five
useful PRs in 8 h 16 min, but:

- the engine stopped 16 times (12 design disputes, 3 "impossible" exits, 1 CI failure) and
  was idle on a person for about three hours;
- the owner sent 30 messages for about 5 real decisions; at least 19 of the 22 points put to
  them were "ok" to the operator's own recommendation;
- in epic #11, 13 of 16 design passes were thrown away, and #21 was built three times.

A post-mortem, run independently by Claude and Codex, converged on one cause underneath the
rest. The loop guarded hard against one failure, an agent claiming "done" when it is not, and
gave no comparable attention to wrong tests, false escalation, recovery, or the owner's
attention. Every deviation from the happy path became `needs_human`:

1. The judge forwarded any objection a critic labelled `changes_criterion` to a person, and
   the engine stopped on any dispute. The judge itself wrote "the criteria are unchanged; this
   note is here only because the objection was marked changes_criterion".
2. The only way to answer was to edit the issue body. Any edit changed the body hash, wiped the
   design and its counters, and started a new design from scratch, which raised new objections.
3. A wrong locked check, a missing system library or a CI failure had no repair path, so each
   became a redesign, a rebuild, or a hand finish.

The owner's direction: an implement trigger goes all the way and solves what it meets on its
own. Merges keep going straight to `main` once the gates pass; runs stay on the host.

## Decision

1. **A run never waits for a person.** `needs_human` is no longer a mid-run state. Each issue
   ends in one of three outcomes, kept distinct in state, labels and the report:
   - **done**: every ledger item is proven; the issue is closed;
   - **delivered**: merged and every item an agent can prove is proven; the remaining items are
     named owner obligations, linked from one owner checklist on the epic. Dependents proceed,
     but the epic is not complete while an obligation is open;
   - **parked**: not delivered; the issue's progress comment carries the diagnosis and what
     resumes it, and every issue that depends on it is parked with it. Independent work
     carries on.
   The owner sees a run twice: the plan at launch and the report at the end.

2. **The judge decides, without dropping requirements.** The ledger as it stands when an issue
   enters design is its requirements snapshot, with stable item IDs. The judge chooses how each
   item is read and proven, within the ADRs and AGENTS.md, but may not drop or weaken an item.
   When two items truly contradict, it takes the reading that keeps the most of both and records
   the part it cannot honour as an owner obligation, never as passed. Every reading is recorded
   with its reason in the PR's "Decisions" section and in the run report, and the cross-vendor
   reviewer checks those decisions against the original items. Critics and auditors raise
   objections; they no longer label them as escalations. The owner overrides after the fact by
   editing the issue (reopening it first if it is closed), and the next run picks that up.

3. **Edits amend; work is kept.** A changed issue body triggers a judge pass that amends the
   previous design, with the previous decisions as input. Checks the new design no longer needs
   are superseded and unlocked in the engine and in the CI guard alike; work already written is
   kept as the next implementer's starting point. The recovery budgets (redesigns, check
   amendments, CI fixes, fix-forwards, merge refusals) persist across restarts and the engine's
   own redesigns; only an owner's edit, which is new evidence, resets them. Each new design gets
   its own bounded implement attempts and fix rounds. Starting over is a deliberate `--fresh`,
   never a side effect.

4. **Every failure class has a bounded recovery path.**
   - A check the implementer shows to be wrong: an independent agent tries to reproduce the
     defect; if it does, the check's author amends that check and it is locked again.
   - Verification keeps failing: one redesign with the failure notes, then the issue parks.
   - A red `required` check is re-run once on the same head, and its own new verdict awaited
     (a flaky failure clears). Still red: a check that gave no verdict (cancelled, missing,
     timed out waiting) parks as an outage; a real failure goes back to the implementer with
     the failed log. CI is never made green by weakening a requirement.
   - Review findings keep three states. Reproduced: fixed in a fix round. Disproved: dropped.
     Unresolved: recorded as advisory in the PR, not filed.
   - An engine error: caught, written to a local journal, and filed as one GitHub issue per
     fault fingerprint through a deduplicated outbox; the item parks. A failure to file stays
     local. State the engine cannot trust stops publication: the one stop that remains.
   An unchanged failure is never retried without new evidence. Switching the implementing
   vendor and splitting an issue into chunks are later steps of the ladder, added after a pilot:
   both need review assigned by actual authorship and proof that every item is kept.

5. **The environment heals itself on the host, from checked-in recipes.** The doctor probes what
   the run will use (it launches Chromium and runs each test entry point) and repairs only
   through pinned, allowlisted recipes under `setup/`: `npm ci` with lifecycle scripts off
   unless a package needs them, Playwright's browsers, uv-managed Python and pinned pytest, and
   missing shared libraries fetched with `apt-get download` and unpacked with `dpkg -x`. Repairs
   are staged, smoke-tested, then activated, keeping the previous working copy. Unpacked
   libraries reach only the browser subprocesses, never shell profiles, the engine, `gh` or
   other agents. One environment failure is diagnosed once for every issue it affects. What
   still needs root goes on the owner checklist and parks only the deliverables that depend on it.

6. **Proof matches the item.** An item is proven by a durable test (committed and run by CI),
   a one-shot command (recorded evidence, not committed), or an agent review (recorded in the
   PR), and may use more than one. Prose is reviewed, not keyword-matched. `manual` is only for
   what no agent can do (credentials agents do not hold, real-world rehearsals) and must say
   why; manual items become owner obligations (decision 1).

7. **Issues are classified, not rewritten.** Before design, each ledger item is classified
   (agent-provable, agent review, or owner) as metadata in the run state. The issue text is not
   changed and every original item stays in the ledger. Rewriting issue text is deferred until
   item conservation and live graph updates are proven.

8. **The gates that make autonomy safe stay, and one is added.** The `required` CI check on the
   exact head, cross-vendor review with independent reproduction of findings, head-SHA-bound
   merges, one revertible PR per issue, commit-bound evidence, and the decision log all stay.
   Added: after each merge, the durable tests of the epic's earlier issues run on `main` before
   dependents are released (a later issue broke an earlier issue's evidence unseen in epic #11).
   A gate is kept when it names a concrete failure mode, costs in proportion to it, and has a
   test; one that has not yet fired is not removed for that reason alone.

9. **The operator is thin.** The `implement` skill launches the run, waits on its events and
   writes the final report. It never relays questions during a run and never edits issues,
   branches or checkboxes.

## Implementation

Delivered in stages, each tested against the recorded failures of the 2026-10-04 runs:

- **First (engine 0.2.0):** decisions 1, 2, 4, 8 and 9 in full; decision 3 except the amendment
  pass (a changed design is redone with the previous decisions as input, keeping the branch,
  the work and the budgets, and retiring the checks it drops); decision 5's probes, staged
  repair and library recipe; decision 6's owner obligations (manual items no longer hold up
  dependents, are collected in one owner checklist, and the issue closes once the owner ticks
  them).
- **Next:** decision 3's amendment pass, decision 6's three kinds of proof, decision 7, a
  slimmer default design (one proposal and one cross-vendor audit for ordinary issues), then
  switching the implementing vendor and splitting an issue, after a pilot run.

## Consequences

- A run ends with merged work, a decision log, parked items with follow-up issues, and one
  owner checklist, instead of a trail of stops.
- A wrong judge decision can reach `main`. It is visible in the PR and the run report,
  revertible like any merge, and corrected by editing the issue and re-running. Its reach is
  bounded by decision 2: no requirement disappears, at worst it becomes an owner obligation.
- "Delivered" is not "done": an epic whose issues are all delivered still shows the owner
  obligations it is waiting for.
- On a host without root, deliverables that need a system package no recipe can unpack are
  parked until the owner installs it; the rest of the epic proceeds.
- Session 1 issues that need real-world measurement, rehearsals with people, private reference
  material or credentials agents do not hold will end as delivered, not done.

## Alternatives considered

1. **Keep stopping, but ask better questions.** Rejected: the post-mortem showed the questions
   were almost always answered with the operator's own recommendation; better phrasing does not
   remove the wait.
2. **A precedence order (epic, then ADRs, then issue, then checkbox) for the judge.** Rejected:
   it lets a broad objective override a precise requirement. Decision 2 bounds the judge by the
   ledger instead.
3. **Merge into an epic branch, one final PR.** Rejected by the owner: later work could not
   build on earlier issues until the end, and per-issue PRs already keep each change revertible.
4. **Run the loop in a container.** Deferred: it would remove most environment failures and
   ADR 0008's isolation limit, but needs Docker or Podman on the host. The recipes in decision 5
   are written so a container image can reuse them later.
