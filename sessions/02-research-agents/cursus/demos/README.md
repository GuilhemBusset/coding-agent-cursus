# Research loop demos

Open [research-loop.html](research-loop.html) directly from disk. All four bundles
are public in [fixtures/research-loop](../fixtures/research-loop/manifest.json).
They are **synthetic executions**, generated 15 November 2026: prescribed model
answers and usage through the actual Pi program, tools, accounting and grader.
The EV dossier and its timings/costs are fictional. No captured-live success,
model efficacy, calibrated budget or classroom rehearsal is claimed.

## Prepare and inspect

All commands below run from `sessions/02-research-agents/` after its pinned
[setup](../../../../setup/README.md#session-2-python-and-pi-toolchain):
Node 24.15.0, Python 3.12, locked uv and npm dependencies. Prefix commands with
`mise exec --` if these tools are not already on PATH. Viewing HTML needs no
setup, service, account or package installation; runtime setup is for execution.

```sh
uv run --locked python -m cursus.demos.research_loop prepare
```

Exit 0. Prints a fresh `exercises/runs/teaching-<id>/` output directory.
The helper stages completed checkpoints in an automatically removed temporary
workspace; it never replaces student `harness/` or `prompts/`. Use
`--output exercises/runs/teaching-demo` for a predictable, **unused** directory.
It executes these four real checkpoint interfaces and seals the artifacts with
the existing replay contract (integrity since sealing, not authenticated origin):

| Bundle | Runnable checkpoint / case / fault | Observe in its output |
| --- | --- | --- |
| `a-gap` | `00-model`, `a-find` | `requests.jsonl`: no tools; score 0/10 facts despite `completed` |
| `b-memory` | `03-memory`, `b-compare` | Last `memory-context.jsonl` and outbound request: EV-S06 corrects S05; S07/S08/S09 are one EV-E-Q1 group; independent Q2 |
| `c-rows` | `04-audit-stop`, `c-audit` | `tool-results.jsonl`: actual check_table pairs/rows, exclusions and denominator; last context retains them; claims withhold uncertain-demand superiority |
| `recovery` | `04-audit-stop`, `a-find`, `transient-read` | `trace.jsonl`: failed tool-1, identical successful tool-2 with retry_of, then further research; 7 model / 8 tool calls, 1 service error |

Open `report.md`, `claims.json`, `scorecard.json` and the public case's
`reference.json` side by side. Grade independently, then audit prose support.
Search results are discovery; read spans and calculator rows are support.
For the model payload inspect `requests.jsonl`, not an imagined context history.
The HTML stepper is a readable snapshot of these bundled artifacts, not a second
agent simulator. It displays cumulative counters, actual events and final claim
citations; the raw request and memory disclosures show the real values.

## Offline outage fallback

Use the bundles even when a provider, credentials or student edits fail. These
commands need only the session's Python environment, never the Node/Pi runtime
or network. Choose new output names on reruns. Each returns exit 0, including A's
truthful low-quality result; replay validity is distinct from the research grade.

```sh
uv run --locked python -m exercises.fixed.replay --run cursus/fixtures/research-loop/a-gap --out exercises/runs/teaching-replay-a
uv run --locked python -m exercises.fixed.replay --run cursus/fixtures/research-loop/b-memory --out exercises/runs/teaching-replay-b
uv run --locked python -m exercises.fixed.replay --run cursus/fixtures/research-loop/c-rows --out exercises/runs/teaching-replay-c
uv run --locked python -m exercises.fixed.replay --run cursus/fixtures/research-loop/recovery --out exercises/runs/teaching-replay-recovery
```

Outputs explicitly say `evidence_kind: replay`, `source_evidence_kind: synthetic`
and name the original run. Replay revalidates hashes/accounting and regrades saved
claims. It does not ask a model to research again or establish live compatibility.
The source seal is not proof that the source was captured live.

## Student edit / run / rejoin

The [build deck](../01-build.html) supplies the short explanations; each completed
checkpoint's README supplies the exact edit and say/run/observe/rejoin actions:
[00](../../exercises/fixed/checkpoints/00-model/README.md),
[01](../../exercises/fixed/checkpoints/01-read/README.md),
[02](../../exercises/fixed/checkpoints/02-search/README.md),
[03](../../exercises/fixed/checkpoints/03-memory/README.md),
[04](../../exercises/fixed/checkpoints/04-audit-stop/README.md).

From the session, the full prefix is `uv run --locked python -m exercises.fixed.`.
The deck's shortened `checkpoint rejoin <name>` actions use that prefix.
For example, restore the public solution and run B:

```sh
uv run --locked python -m exercises.fixed.checkpoint rejoin 03-memory
uv run --locked python -m exercises.fixed.checkpoint run 03-memory --case b-compare --offline
```

`rejoin` backs up both editable trees under a unique `exercises/runs/backups/`
path before replacing them. `run` snapshots **current edits**; its checkpoint
argument selects tools/scripts, not a silent solution restore. Omit `--name` for
fresh names. Existing student work is not changed by instructor `prepare`.

## Stops

After completing or rejoining 04, run the announced faults (exit 0 means artifacts
were produced, not quality success):

```sh
uv run --locked python -m exercises.fixed.checkpoint rejoin 04-audit-stop
uv run --locked python -m exercises.fixed.checkpoint run 04-audit-stop --offline --scenario transient-read
uv run --locked python -m exercises.fixed.checkpoint run 04-audit-stop --offline --scenario repeated-retrieval
uv run --locked python -m exercises.fixed.checkpoint run 04-audit-stop --offline --scenario missing-source
```

The transient failure retries once, then continues. Repetition stops after three
identical reads (one new span, then two without growth): `no_progress`. Permanent
absence stops immediately: `service_error`, no retry. Inspect partial reports,
retained spans, final run_end and failed assertion IDs. The default 12-model /
20-tool / 30,000-token ceilings are provisional, pending pilot calibration.
Fault runs use development support, recorded in their config, rather than claiming
the older pinned rating export supplies fault metadata. All failed work counts.

## Experiments

Only after 04 and the 65–70 break: driver B proposes a harness change at fixed
prompts (70–85), then A freezes code for the original prompt pair and B drives
the announced paraphrases (85–105). Both audit grades/prose at 105–120. These are
planned allocations, not observed classroom timings.

Run the existing completed comparisons, with fresh directories:

```sh
uv run --locked python -m exercises.fixed.evaluate compare --experiment exercises/fixed/examples/harness.json --output exercises/runs/teaching-harness
uv run --locked python -m exercises.fixed.evaluate compare --experiment exercises/fixed/examples/prompt.json --output exercises/runs/teaching-prompt
uv run --locked python -m exercises.fixed.evaluate compare --experiment exercises/fixed/examples/paraphrases.json --output exercises/runs/teaching-paraphrases
```

Each intentionally exits **1**, a valid rejection, not an execution error. Exit 2
invalidates the comparison. The harness candidate stops after discovery before
retained evidence grows: all A–C regress, so revert despite fewer tokens. Both
prompt comparisons have equal scripted quality/resources: keep the simple baseline.
Those scripts cannot establish a live model's sensitivity to wording.

Use [harness-experiment.md](../../exercises/fixed/examples/harness-experiment.md)
and [the prompt sequence](../../exercises/fixed/examples/README.md#prompt-experiment--minutes-85105)
for exact snapshot/configure/edit commands. Inspect `comparison.json`, `shared.json`,
each trace and request, and `peer-review.md`. Fill
[experiment-notes.md](../../exercises/experiment-notes.md). The
[completed records](../../exercises/fixed/examples/completed-records.md) retain
all-attempt resources and limits; their peer prose review remains pending.
Rejoin the accepted baseline before continuing:

```sh
uv run --locked python -m exercises.fixed.examples.workflow rejoin harness-baseline
uv run --locked python -m exercises.fixed.examples.workflow rejoin prompt-vague
```

The [sources and fact check](../sources.html) distinguish the published methods
from these classroom choices. Live/API, cap calibration and classroom evidence
belong to the separate pilot/readiness work, not a pass inferred from this demo.
