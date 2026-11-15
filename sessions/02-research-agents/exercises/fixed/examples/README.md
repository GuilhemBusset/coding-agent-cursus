# Controlled experiments, public completed examples

First build the same program through [checkpoint 04](../checkpoints/04-audit-stop/README.md),
then run the [70–85 harness block](harness-experiment.md). Only then start the
85–105 prompt block below. This directory supplies completed **editable** snapshots,
shared comparison specifications, synthetic provider scripts and
[filled records](completed-records.md). Student edits go in `exercises/harness/`
and `exercises/prompts/`; outputs go in `exercises/runs/`.

Every snapshot has a verified `snapshot.json`, complete runnable checkpoint-04
code and exactly one active prompt (`prompts/system.md`, plus empty `.gitkeep`).
No prompt guide or competing prompt is included in model context. Source copies
are public at class start; the rejoin helper copies either complete directory,
preserving existing work in a unique backup before replacement.
Both block guides live here in `fixed/examples/`, outside the replaced editable
trees, so checkpoint and experiment rejoin commands leave the instructions available.

| Snapshot in `versions/` | Purpose |
| --- | --- |
| `harness-baseline` | Completed checkpoint 04; shared prompt clarifies prefixed variant IDs |
| `harness-candidate` | Same prompt; no-progress threshold reduced from two to one |
| `prompt-vague` | Original completed code; vague request |
| `prompt-structured` | Identical code; question, scope, evidence, uncertainty, output |
| `prompt-vague-paraphrase` | Same code; announced rewording of the vague request |
| `prompt-structured-paraphrase` | Same code; announced rewording of the structured request |

`harness.json`, `prompt.json` and `paraphrases.json` all select the same public
class schedule: A/20261115, B/20261125, C/20261135, one trial each, with corresponding
`public-seed-*` variants. All use `../config/run.v1.json`, the pinned public rating
export, and the **same** scripts A–C. Settings record the initial OpenAI model and
configurable endpoint; no provider switch is part of either experiment. The initial
12/20/30,000 per-run caps remain provisional pending the separate live pilot.
Before saving the two harness snapshots, their shared checkpoint prompt received
the same scope clarification: seeded source IDs have prefixes, so discover exact
IDs rather than guessing the base-case ID. This preparation is identical in both
snapshots; the threshold is the sole variable changed by that comparison.

## Prompt experiment · minutes 85–105

**Say (85–87).** Swap: driver A edits prompts; B audits the frozen code and
records. “Now change instructions only. Predict whether naming the question,
scope, evidence, uncertainty and output will change the answer. Can you identify
an unsupported inference?” Announce both paraphrases **before** the first run;
open all four `versions/prompt-*/prompts/system.md` files. Write the prediction
in [experiment-notes.md](../../experiment-notes.md). Hypotheses may be disproved.

The vague form says “Research the supplied EV dossier question and give a useful
answer.” Its paraphrase says “Look into the given EV research question and write
a helpful response.” The structured form explicitly covers all five dimensions;
its paraphrase preserves them with different wording. Both still receive the
same task question/context and supplied output schemas from the launcher.
The vague prompt is deliberately underspecified, not a guarantee of failure.

**Edit and save (87–91).** Freeze the accepted checkpoint-04 code. Rejoin the
public vague snapshot to get the common starting point (both editable trees are
backed up). Save it, edit **only** `exercises/prompts/system.md` to the structured
form, and save again. Copy the full supplied form with your editor; do not add
both forms to the active prompt directory, because all its files enter context.

```sh
uv run --locked python -m exercises.fixed.examples.workflow rejoin prompt-vague
uv run --locked python -m exercises.fixed.snapshot --name prompt-before
```

After the prompt-only edit:

```sh
uv run --locked python -m exercises.fixed.snapshot --name prompt-after
uv run --locked python -m exercises.fixed.examples.workflow configure prompt --baseline exercises/runs/versions/prompt-before --candidate exercises/runs/versions/prompt-after --output exercises/runs/my-prompt.json
uv run --locked python -m exercises.fixed.evaluate compare --experiment exercises/runs/my-prompt.json --output exercises/runs/my-prompt-comparison
```

**Run and observe (91–95).** Compare `shared.json`, code hashes, per-case scores,
before/after traces, requests, reports and `peer-review.md`. A changed code hash
invalidates a prompt-only comparison before any attempts launch. Correct JSON is
not sufficient: inspect requirement coverage, actual citation spans/rows and prose
support. Keep or revert on the same quality-first rule as the harness block.

For the completed original pair, the same evaluation command is:

```sh
uv run --locked python -m exercises.fixed.evaluate compare --experiment exercises/fixed/examples/prompt.json --output exercises/runs/prompt-example
```

**Swap paraphrases (95–101).** Driver B takes over; A checks frozen controls.
Use the already-announced rewordings, not a newly tuned prompt after seeing scores.
Change only the prompt to the vague paraphrase, save, then change it to the
structured paraphrase and save. Keep the exact harness code from the first pair:

```sh
uv run --locked python -m exercises.fixed.examples.workflow rejoin prompt-vague-paraphrase
uv run --locked python -m exercises.fixed.snapshot --name paraphrase-before
```

After copying the structured paraphrase into `exercises/prompts/system.md`:

```sh
uv run --locked python -m exercises.fixed.snapshot --name paraphrase-after
uv run --locked python -m exercises.fixed.examples.workflow configure paraphrases --baseline exercises/runs/versions/paraphrase-before --candidate exercises/runs/versions/paraphrase-after --output exercises/runs/my-paraphrases.json
uv run --locked python -m exercises.fixed.evaluate compare --experiment exercises/runs/my-paraphrases.json --output exercises/runs/my-paraphrases-comparison
```

The public rejoin uses byte-identical checkpoint-04 code across both pairs. If
using your own accepted code instead, preserve it and replace **only** the prompt
with your editor; check the code hash against the first pair. Public completed rerun:

```sh
uv run --locked python -m exercises.fixed.evaluate compare --experiment exercises/fixed/examples/paraphrases.json --output exercises/runs/paraphrases-example
```

**Compose and rejoin (101–105).** Fill one record per pair. In both supplied
comparisons, quality and scripted resource totals are equal. Exit **1** and
`revert` mean there is no measured gain supporting adoption, not that structured
prompts are harmful. Keep the simple baseline; retain the lesson that these scripts
cannot test a model's sensitivity to wording. Inspect the outbound requests to
verify the prompt changed even though the script delivered identical answers.
To rejoin at any point, use `rejoin prompt-vague`, `rejoin prompt-structured`,
`rejoin prompt-vague-paraphrase` or `rejoin prompt-structured-paraphrase`, then
continue the matching public comparison above. Finish with the filled record and
one before/after trace ready for the 105–120 evaluation block.

## Evidence and reruns

All three examples are **synthetic scripted executions**, including their answers,
token/cache/reasoning counts and quality outcomes. Real Pi orchestration, public
tools, independent accounting and the pinned grader run locally; `scripts/*.json`
provides predetermined Responses events and usage, regardless of prompt. C actually
calls the public table checker on its announced variant; it does not reuse base-case
numbers. No example is a replay of captured-live events. There are **no live model
results or efficacy claims** here. Peer prose review remains pending in generated
scorecards until the pair records its audit. Timing allocations are not rehearsal
measurements.

Run commands from the session after its pinned setup. All documented comparisons
use new output directories; on reruns choose new names. Exit 2 means invalid input,
not a low score. The evidence tests run these same examples in temporary directories,
print results before cleanup and need no credentials:

```sh
mise install node@24.15.0
mise exec node@24.15.0 -- npm ci --ignore-scripts --no-audit --no-fund
mise exec node@24.15.0 -- uv run --locked pytest -s tests/labs/test_experiment_workflow.py
```

For separately authorized live classroom runs after the live setup/pilot, make a
new experiment JSON with the saved baseline/candidate paths, **remove `scripts`**,
and run the same `evaluate compare` command with `--live`. Supply credentials only
through the environment as described in the session setup. Keep shared settings,
seeds, cases and budgets unchanged within and across the paraphrase pair, retain
all attempts, inspect prose and record findings as captured live. Do not turn this
optional procedure or an unavailable live check into a reported pass.
