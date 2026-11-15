# Harness experiment · minutes 70–85

Complete [checkpoint 04](../checkpoints/04-audit-stop/README.md) first:
read/search, claim–passage memory, numerical checking, recovery and stopping
belong to the same runnable program. Leave its failing trace visible over the
65–70 break. Prompt experiments start at 85, after this block.

Commands run from `sessions/02-research-agents` after the
[pinned session setup](../../../../../setup/README.md). On all three student OSes,
use the session's Node 24.15.0 and `uv run --locked`; no shell-specific copy or
environment assignment is needed. New run/version names must be unused.

**Say (70–72).** Driver B takes the keyboard; A navigates and checks controls.
“Predict one harness change. What quality requirement will it fix, or what work
will it save? What earlier case could regress?” Write the hypothesis in
[experiment-notes.md](../../experiment-notes.md) before editing. Hold every prompt
byte, model/provider/endpoint, sampling setting, case/seed/trial, registered tool
and budget fixed. We adapt Harness²'s Propose–Probe–Compose: students propose,
public checks probe, and the pair composes one trace-supported lesson. Harness²'s
task-level refinement instead probes without ground-truth feedback.

A simple baseline may already pass. Inspect why; keeping it and recording the
evidence is a valid outcome. Do not add memory, retries or extra loops merely
to make the experiment look substantial.

**Edit (72–75).** Save the current complete `harness/` and `prompts/` first:

```sh
uv run --locked python -m exercises.fixed.snapshot --name harness-before
```

Change one policy in `exercises/harness/`, predict its effect, and save again:

```sh
uv run --locked python -m exercises.fixed.snapshot --name harness-after
uv run --locked python -m exercises.fixed.examples.workflow configure harness --baseline exercises/runs/versions/harness-before --candidate exercises/runs/versions/harness-after --output exercises/runs/my-harness.json
```

For the public worked proposal, change only `stagnant >= 2` to `stagnant >= 1`
in `harness/policy.ts`: “Stopping after one retrieval adds no retained evidence
will save tokens without losing answers.” The
[completed candidate](versions/harness-candidate/harness/policy.ts)
contains that single edit. The fixed boundary still owns resource admission;
this edit changes the student stopping policy, not the measured budget.

**Run (75–78).** Use one comparison command for both saved versions, with the
public A–C class schedule and a fresh workspace for every attempt:

```sh
uv run --locked python -m exercises.fixed.evaluate compare --experiment exercises/runs/my-harness.json --output exercises/runs/my-harness-comparison
```

The helper retains the shared public settings, pinned rating export and synthetic
scripts. For an immediately runnable completed comparison, use the same evaluator:

```sh
uv run --locked python -m exercises.fixed.evaluate compare --experiment exercises/fixed/examples/harness.json --output exercises/runs/harness-example
```

Exit **1** is expected for this completed example: the valid candidate regresses
quality and must be reverted. Exit 0 means machine retain gates passed; exit 2
invalidates the comparison. An unintended prompt edit is rejected before runs.
Never change a grader, discard a failed attempt or edit a saved snapshot to pass.

**Observe and compose (78–83).** Open `comparison.md`, `before.md`, `after.md`
and `shared.json` in the comparison directory. Inspect
`runs/baseline-01/trace.jsonl` beside `runs/candidate-01/trace.jsonl`, their
`tool-results.jsonl`, `requests.jsonl`, reports and failed assertions. Follow a
claim to its source via `peer-review.md`; machine citation checks do not replace
the prose support audit. Inspect C's calculator and rows as well as earlier A/B.

In the synthetic worked example, scope read → search is legitimate discovery,
but search adds no **retained evidence**. The candidate mistakes that for a stall
and stops before source reads and synthesis. Baseline completes all three cases;
candidate completes none, despite lower measured scripted tokens. Revert the
threshold change. Retain the lesson: one discovery step without new memory is
not enough to establish no progress. Record hashes, quality, all-attempt resources
and the trace supporting this claim. These scripts prescribe model outputs and
usage; the observation concerns execution of this policy on these scripts only.

**Rejoin (83–85, or whenever stuck).** Restore the public completed baseline,
then continue from its original stopping policy. The command preserves both
editable directories under a unique `exercises/runs/backups/` directory first:

```sh
uv run --locked python -m exercises.fixed.examples.workflow rejoin harness-baseline
```

To inspect the rejected proposal, rejoin `harness-candidate`; restore
`harness-baseline` before prompting. The [six public snapshots and completed
records](README.md) are available from the start. At 85 swap
roles and [freeze code for the prompt experiment](README.md#prompt-experiment--minutes-85105).
