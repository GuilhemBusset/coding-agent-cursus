# 04 · Check numbers, recover once, stop explicitly — minutes 45–65

This completed checkpoint, its helpers and synthetic scripts are public from
the start. Commands below run from `sessions/02-research-agents` after its pinned
setup. Driver A edits; driver B follows the evidence and stop decisions. Keep
the saved prompt, model and settings fixed for the harness comparison.

**Say (45–48).** Instructor prompt: “Method B is 20% cheaper than A. Which rows
are we comparing, what is the denominator, and does this say anything about
uncertain demand? Add the calculator, then make the program decide when it can
finish and when it must stop. A retry is work, so it spends the same budget.”
Open case C's question, `EV-S13` protocol, `EV-T01` table and `EV-S14` boundary.
The two complete feasible pairs use rows 1–4: A totals 300, B totals 240 fictional
cost units, so `(300 - 240) / 300 = 0.2 = 20%`. Exclude the entire infeasible pair
and both unpaired executions. Neither the percentage nor P01 context supplies
an uncertain-demand experiment. That conclusion remains unknown; the next
experiment needs matched uncertain-demand scenarios and independent repeats.

**Edit (48–54).** First copy this checkpoint's `prompts/system.md` into your
editable `exercises/prompts/system.md` with your editor. It corrects one source
pointer: EV-S01 starts A/B, while C starts EV-S13 (C has no EV-S01). This is a
scope correction, not a prompt experiment. Freeze this corrected prompt in
**both** saved versions. Save your 03 harness before editing it:

```sh
uv run --locked python -m exercises.fixed.snapshot --name before-audit-stop
```

Continue the same `harness/main.ts`. The exact final edit is the adjacent
[`harness/main.ts`](harness/main.ts); compare it side by side with 03 and copy
its import, Runtime tool-name union and `run` body into your editable file.
Keep your existing `memory.ts`; copy this checkpoint's updated
[`memory.ts`](harness/memory.ts) if you rejoined 03, and copy
[`policy.ts`](harness/policy.ts) into `exercises/harness/`. Both are already in
the original student scaffold. These are editable student policy, not a grader.
The full rejoin below performs the same replacement if time is short.

Walk through the small connections before running:

- Add `api.researchTool('check_table')` to the Agent's tools when supplied by the
  case registry. A/B supply read/search; C additionally supplies the calculator.
- In `afterToolCall`, retain passages and `retainCalculation(args, result.details)`.
  Keep the requested filter, actual pairs/row spans, values, units, totals and
  baseline denominator, not just the percentage. `memory-context.jsonl` indexes
  the **actual next outbound request** containing that evidence. Full row and
  execution IDs also remain in the fixed `tool-results.jsonl` audit.
- Call `policy.before` before a tool; call `policy.observe` after it with whether
  retained evidence grew. Two consecutive successful retrievals adding nothing
  stop with `no_progress`; search snippets alone are discovery, not support.
- A retryable read error sets one pending identical request. The next model
  context asks for that retry; the before hook admits only those arguments.
  Another error for that request stops with `service_error`, even if retryable.
  Permanent errors stop immediately with partial evidence. No budget resets.
- The final branch parses JSON, calls `validateOutput` against the supplied
  public schemas, checks unique claims and visible anchors, and only then returns
  `completed`. Broken JSON/shape/anchors return `invalid_output` with diagnostics.
  A pending retry is not completion. `partialOutput` retains evidence for stops;
  it never manufactures a successful research conclusion.

The fixed boundary continues to enforce admission before dispatch and preserve
model/tool/token errors. Pi can catch a rejected tool internally, so the wrapper
keeps its boundary stop reason for the partial report. A mixed tool batch cannot
restart work after the policy has stopped. Structural completion remains separate
from the independent factual grade and peer prose review.

**Run and inspect (54–58).** Save the edited harness, then run C and compare A–C:

```sh
uv run --locked python -m exercises.fixed.snapshot --name with-audit-stop
uv run --locked python -m exercises.fixed.checkpoint run 04-audit-stop --case c-audit --snapshot exercises/runs/versions/with-audit-stop --offline --name audit-c
uv run --locked python -m exercises.fixed.checkpoint compare --audit-stop --baseline exercises/runs/versions/before-audit-stop --candidate exercises/runs/versions/with-audit-stop --output exercises/runs/audit-abc
```

Choose new names on subsequent runs. Open `audit-c/report.md`, `claims.json`,
`candidate-output.json`, `tool-results.jsonl`, `memory-context.jsonl`,
`runtime-status.json` and the final `run_end` in `trace.jsonl`. Follow the row
citations back to the CSV, then locate the separate scope claim and uncertainty.
Compare failed assertions in `scorecard.json` with the public reference; a correct
percentage with wrong rows or omitted uncertainty must fail. In `audit-abc`,
inspect `comparison.md`, `shared.json` and the per-role traces: A and B stay
passing. Bare `compare` retains checkpoint 03's earlier A/B command behaviour.

These scripts supply worked model outputs, not model reasoning. Even 03 can
receive a correct scripted C answer without executing its unavailable calculator;
a score alone does not prove that capability. Inspect 04's actual calculator
dispatch and retained rows. Normal comparisons use the pinned rating bundle.
The corrected starting prompt and C's script both start at its registered
EV-S13. This offline block does not certify live prompt/model performance.

**Recover (58–62).** Announce the public **transient-read** fixture at
`fixed/config/public/faults/transient-read.json` before activation:

```sh
uv run --locked python -m exercises.fixed.checkpoint run 04-audit-stop --offline --scenario transient-read --name recovered-read
uv run --locked python -m exercises.fixed.checkpoint run 04-audit-stop --offline --scenario repeated-retrieval --name stalled-read
uv run --locked python -m exercises.fixed.checkpoint run 04-audit-stop --offline --scenario missing-source --name absent-read
```

The fault commands use case A's first registered passage (explicit offsets),
except `missing-source`, which reads EV-S01 then requests EV-MISSING. In
`recovered-read`, inspect the failed invocation, its one successful identical
retry with a new tool ID and `retry_of`, then the subsequent search and source
reads. All failed work stays in `dispatches.jsonl`, `trace.jsonl` and independent
`accounting.json`. `stalled-read` stops after the third identical read: one new
span followed by two adding nothing. `absent-read` makes no retry and preserves
the earlier evidence with a `service_error` stop, rather than claiming success.
Fault schedules are synthetic **development-support** runs through the same
launcher/accounting/grader; their config records the working support hashes.
The older pinned rating bundle has no fault metadata schema, so these are not
labelled pinned rating runs.

The default **12 model / 20 tool / 30,000 token caps are provisional**, pending
live pilot calibration. They are ceilings, not a recommended target. A reservation
can deny the next request before the observed total reaches the cap. Inspect
`reservations.jsonl` and `dispatches.jsonl`, not just a model's token estimate.
`--settings <saved-settings.json>` accepts explicit lower-cap experiments. The
offline tests exercise each boundary, including denied retries after a failed
read; nothing inside a scored run asks a student to intervene.

**Rejoin and leave a trace (62–65).** From any earlier checkpoint or a fresh
workspace, restore both complete editable directories with one command:

```sh
uv run --locked python -m exercises.fixed.checkpoint rejoin 04-audit-stop
uv run --locked python -m exercises.fixed.checkpoint run 04-audit-stop --case a-find --offline
uv run --locked python -m exercises.fixed.checkpoint run 04-audit-stop --case b-compare --offline
uv run --locked python -m exercises.fixed.checkpoint run 04-audit-stop --case c-audit --offline
```

Rejoin backs up harness **and prompts** under a unique `exercises/runs/backups/`
path before replacing either. `run` executes current edits (or `--snapshot`);
it never silently restores the solution. At 65, leave `stalled-read/trace.jsonl`
on screen beside its partial report and failed assertions: three retrievals,
one distinct evidence span, `no_progress`, zero interventions. Keep that failure
visible during the 65–70 break for the next controlled experiment.

Offline validation (temporary workspaces, no API calls):

```sh
uv run --locked pytest tests/labs/test_final_checkpoint.py
npm run typecheck
```

The 20-minute sequence is a teaching allocation, not an observed rehearsal or
cap calibration. Those measurements remain part of the separate pilot.
