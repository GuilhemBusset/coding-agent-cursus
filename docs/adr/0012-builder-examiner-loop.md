# ADR 0012 — The implement loop solves what it finds: builder and examiner, no parking

- **Status:** Accepted
- **Date:** 2026-10-17
- **Deciders:** Guilhem Busset (instructor / repo owner)
- **Context:** [ADR 0008](0008-implement-loop.md), [ADR 0011](0011-autonomous-implement-loop.md), [ADR 0007](0007-required-ci-gate-and-merge-forward-shipping.md), [ADR 0010](0010-platform-support.md)
- **Supersedes:** ADR 0008 decisions 2 and 3 (roles by vendor; checks written before code, every
  expected test must run, a reproduced review defect blocks whatever its priority); ADR 0011
  decision 1's `parked` outcome, decision 3's carry-over of recovery budgets across redesigns,
  decision 4's redesign-then-park ladder, and the conflict policy recorded in #74 (a conflict
  charged as a fix round)

## Context

Between 2026-10-04 and 2026-10-16 the loop ran 13 times on Session 1's issues: 816 Claude agent
calls, $433 of Claude and about 150 million Codex tokens for 23 merges, with 19 parks and 15
redesigns. The issues were small course-material tasks. The owner unblocked parked work by
hand: 12 issue edits in one run, two descoped issues, a dozen re-launches.

A retrospective read every run's events and every agent's prompt and answer (four independent
forensic reports), then three proposers (two Claude, one Codex) argued for four rounds until all
three accepted one design. The findings:

- **The agents were right; nothing let them act.** Implementers filed 37 "impossible" or
  "the check is wrong" reports across the runs; all that were tested were reproduced, and most
  named the exact fix. Only the judge could change the design, only at design time, reading
  `main` instead of the branch, and each use spent the one redesign. Every inconsistency found
  later had no owner and ended in a park. 8 of the 10 exhausted parks trace to contradictory
  artifacts or the verifier's own bookkeeping, none to an agent failing the task.
- **The redesign manufactured the contradictions it was meant to fix.** It deleted locked tests
  the new design's commands still ran (#24, #30, #40, #41, #42), dropped files the kept work had
  changed although the engine logged them (`design_may_miss_paths`, 22 times; #30, #42, #78), and
  carried the amendment budget over so the new checks could not be amended once (#28).
- **The verifier's accounting was wrong.** One JUnit report per command, so `pytest A && pytest B`
  lost A's results (#37, #30); every test in a check file was "expected", including tests no
  command selects (#37's laptop benchmark).
- **Ceremony dominated.** 16% of calls implemented anything; design took 310, review 265. Every
  one of 64 design rounds raised blocking objections that added requirements the issues never
  asked for (npm trust anchors, laptop benchmarks, byte-pinned prose). Blind check writing in a
  sandbox without network or a browser broke: all 17 disputed checks were really wrong.
- **One uncalibrated reviewer decided convergence.** Codex reported every finding at confidence
  0.97–1.0 and caused all 28 send-backs in the later runs, a dozen of them findings it said
  failed no acceptance criterion; with no memory between rounds each round found a new edge.
- **Capabilities the host lacks were treated as defects** (a laptop, native Linux, an API key, a
  rehearsal), and a run exited when another run held the merge queue.

## Decision

1. **Two keys, one per vendor.** The **builder** (the operator's vendor) leads an issue: it plans,
   writes the code, its own tests, the registrations and one command per item. The **examiner**
   (the other vendor) triages the plan, examines and probes the exact head, approves or refuses
   the builder's requests, and certifies the head that may land. A fresh **arbiter** call from the
   examiner's vendor settles disputes, bindingly. Gone: the second proposer, audit, critique,
   judge, blind check writing, the same-vendor acceptance and visual reviewers, the finding
   verifier, check amendments by their author, and redesign.

2. **The issue text is the floor and the ceiling.** The plan gives every item a quoted reading
   and a proof kind: `test`, `command`, `review`, `owner` (only for a capability the host lacks,
   from `loop.toml [host]` plus what the doctor verifies; the agents' part is still built and
   proven) or `deferred` (only to an open issue whose title or body contains the quoted words). The
   engine lints the plan; triage may only point out a misreading, a classification error or a
   dependency, each with a quote, and anything unquoted is dropped. Infra issues also get a failure-
   scenario list.

3. **Tests with the code, independence from probes.** The builder writes its tests with the code.
   The examiner, working in a disposable copy of the head with network and a browser, adds at
   least one independent probe per behavioural item; the engine lints out probes that fail
   unconditionally and runs the rest. Passing probes become locked evidence (`Loop-Probe-Author`);
   a failing one is a finding's reproduction. **Locking happens at the first examination, pass or
   fail**: the builder's tests, test configuration, the selection manifest (what each command ran)
   and every adopted probe. A locked test changes only with the recorded agreement of both
   vendors: a typed `test_change` request and a fresh decision by the other vendor, with fresh
   execution; nothing is retired by omission. The CI guard learns `Loop-Locks:` trailers for files
   locked unchanged.

4. **The engine derives its bookkeeping from reality.** Each pytest process writes its own report
   through a plugin; a test that ran before must keep running; a test in a locked file that no
   command selects needs an explicit disposition (`owner-run` or `excluded: <reason>`). Changed
   paths come from the diff, checked against the plan's zones and approved grants (a path's
   provenance is kept); protected paths (the loop, `.github/`, `.githooks/`, the gate scripts)
   need an approved `protected_change`.

5. **Findings block only when the issue requires them.** A finding blocks when the engine
   reproduces it on the exact head **and** it quotes at least three words of the item it says is
   violated (checked by the engine) or names a safety invariant from `loop.toml`, with a
   behavioural witness (observed against expected). An `unmet` verdict on a `review` item that
   quotes it blocks without a runnable reproduction. Other reproduced findings are fixed in the
   next round if there is one, or filed as one `loop:follow-up` issue per PR. An open finding
   stays open until its reproduction passes or the arbiter rules the item does not require it. The
   examiner reports every finding in one batch, keeps the memory of earlier rounds, and later
   reviews the delta. Self-reported confidence plays no part.

6. **Every merged head is certified.** Whatever changes the head after examination (main merged,
   probes adopted, an approved change) is verified again and certified by a focused delta
   examination. The merge-queue claim is held through push, CI and merge (the ruleset does not
   require up-to-date branches); a run that needs it **waits**, polling, instead of exiting.

7. **No parking.** Outcomes: **done**; **delivered** (merged, every agent item proven; typed
   obligations remain: a capability the host lacks, or an item deferred to another issue, written
   on the issue with a `loop:deferred` label); **waiting** (not terminal: the merge queue or an
   issue another run holds, CI with no verdict, a vendor or GitHub outage, an environment the
   doctor can repair, a new engine version after a fault); **failed** (a ceiling spent with
   blocking defects open, or untrusted state: explicit non-delivery, never a partial merge, filed
   as a loop fault, revived once with a fresh ceiling by a new engine version). After a merge, a
   broken `main` gets one fix-forward, then a revert PR through the same gates.

8. **Budgets are ceilings, rounds are judged by progress.** Every answered agent call is charged
   to a persistent per-issue ceiling (S 20, M 30, L 45 calls; infra issues ×1.5); every timeout or
   crash to a separate infrastructure budget (10 attempts); an outage to neither (the issue
   waits). A round is productive when what fails changes; two unproductive rounds bring a replan
   on the branch, two more end the issue `failed`. Conflicts with `main` cost no round. A per-run
   ceiling stops new calls. Only an owner's edit resets the budgets.

9. **Dependencies found mid-run.** A reviewed dependency waits for its prerequisite when it is in
   the run. In an epic run the launch plan says the run may add open prerequisites from the epic;
   such an issue joins the run with its own PR and the same gates. Otherwise the item becomes a
   `deferred:#N` obligation: the rest lands as delivered, and the item reopens by itself when #N
   lands. Repo-wide per-issue claims keep two runs from working the same issue.

10. **The supervisor makes resumption real.** `scripts/implement.sh supervise <root>` (what the
    operator skill launches, detached) runs the engine until every issue is terminal: it
    fast-forwards the main checkout so new engine versions apply, waits out outages until the
    vendor answers the doctor's smoke call, relaunches crashed runs, and runs **one repair run per
    loop fault** on the fault issue the engine wrote (with a standard ledger: a regression test,
    the fix, a version bump). Bounded: 10 runs and 24 hours per supervision, never raised. A repair
    run may not change the **safety surface**: the verifier's lock, tamper and accounting code, the
    gate module, the live adapter's environment and sandbox flags, `config.py`'s ceilings,
    `loop.toml`'s capabilities and invariants, the supervisor, the CI guard, `.github/`,
    `.githooks/` and the repository rulesets. A fault whose fix needs them stays filed for the owner.

11. **Same access for both vendors.** Codex's working roles run without its sandbox, like Claude
    Code's (`--sandbox danger-full-access`), with the same scrubbed environment (no GitHub
    credentials) and a private git directory per call. A sandbox limitation is an engine problem,
    not an owner obligation. This keeps ADR 0008's trust limit: agents run as the user.

## Consequences

- A smooth issue costs about five calls (plan, triage, build, examine, and the explorers shared
  by the run) instead of a median of fourteen.
- The recorded parks have a defined autonomous path: #24, #30 and #37 deliver with their real-
  world evidence left to the owner; #28, #40, #42 and #78 keep their locked tests and their kept
  work; #41 waits for #47 or defers that item; #34's branch is restored; a run waits for the
  merge queue.
- `failed` remains: a terminating loop cannot promise to finish every task. It is rare (two
  unproductive rounds after a replan, or a spent ceiling), visible, filed as a loop fault, and the
  loop tries once more on its next version.
- A wrong decision of the builder or arbiter can reach `main`; it is published in the PR's
  Decisions section, bounded by the issue text and the safety invariants, and revertible.
- Reproduced findings no item requires no longer block; they are kept in follow-up issues.
- The engine guards against agent mistakes: checks, probes and reproductions run in throwaway
  copies on private git directories; agent-supplied paths and directories that leave the tree,
  name `.git`, or go through a link are refused; files the engine writes for an agent replace
  their directory entry instead of writing through it. These are not a sandbox: an agent runs as
  the user, so one determined to do harm can act on the user's files directly. Strong isolation
  still needs a container (ADR 0011, alternative 4).
- The repository change that goes with it: Node test suites are discovered by glob instead of two
  hand-kept registries, and the session pytest suites run in the `required` CI.

## Alternatives considered

1. **Fix the bugs, keep the pipeline** (raise caps, reset budgets, network for the check author).
   Rejected: most recorded failures could not be repaired by the role that got another try, and
   the ceremony and scope inflation would stay.
2. **A standing steward agent with authority over the design.** Rejected: deterministic rules plus
   typed requests decided by the other vendor cover every recorded case with less authority.
3. **An execution broker for sandboxed agents.** Rejected: giving both vendors the same access is
   simpler, and the broker cannot be reached by Codex mid-task.
4. **Continuation issues and partial merges at the ceiling.** Rejected: they would label unfinished
   agent work as delivered.
5. **Switching the builder's vendor after repeated failure.** Deferred until after a pilot: it
   needs authorship-scoped review.
