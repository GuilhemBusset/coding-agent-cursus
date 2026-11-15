# 00 · Model call — minutes 0–10

**Say.** “What can this model actually know? Predict its answer to A. We already
have a runnable program: Pi owns the conversation; the supplied adapter connects
it to the model and meters requests. Today we build the harness before changing
the prompt.” Driver A runs; driver B watches the trace and records the prediction.

**Start/edit.** From the session folder (`sessions/02-research-agents/`), complete
the session README setup first: pinned Node/Python, `uv sync --locked`, `npm ci`.
Use `mise exec --` before commands if the pinned tools are not already on PATH.
Open `exercises/harness/main.ts`: `const tools: AgentTool[] = [];` registers no
research tools. Read the short Agent construction, `agent.prompt` and JSON output
lines; no edit is required to get a first result. Leave
`exercises/prompts/system.md` fixed through checkpoints 00–02.

**Run.** This credential-free smoke uses explicitly **synthetic scripted model
responses**, not a recorded live failure:

```sh
uv run --locked python -m exercises.fixed.checkpoint run 00-model --offline --name baseline-A-synthetic
```

The same entry point, `harness/main.ts`, runs in a fresh workspace. The helper
prepares shipped public support, saves both editable directories under
`exercises/runs/versions/baseline-A-synthetic/`, runs A and grades afterwards.
Keep that version and `exercises/runs/baseline-A-synthetic/` as the baseline.
Names cannot overwrite runs; omit `--name` for a new unique name on reruns.

**Observe.** Open that output folder: `report.md` is the answer,
`requests.jsonl` shows one outbound model call with no tools, `trace.jsonl` and
`accounting.json` show one model attempt and zero tool invocations. Check
`config.json` for `evidence_kind: synthetic`. Open `checkpoint-comparison.json`,
then `exercises/cases/a-find/reference.json` and `scorecard.json` side by side.
The scripted baseline explicitly withholds dossier findings; inspect which
method-set, capacity and assumption requirements remain unmet. This demonstrates
the pipeline, not a claim that a live model must fail. For a live baseline, compare
what actually happened, even if correct; ask whether each citation is supported
by evidence in its trace. No tool result means no retrieved dossier evidence.

**Live option.** With authorized API spending and `OPENAI_API_KEY` in the
environment, replace `--offline` with `--live` and choose a separate name such as
`baseline-A-live`. Never put credentials in files. `--settings` accepts a copy of
`fixed/config/run.v1.json`; provider/model/endpoint alias remain configurable,
with endpoint URLs supplied through the documented adapter environment variables.
Live compatibility and classroom timing evidence are captured in pilot #195;
synthetic artifacts do not certify either. Run artifacts label live separately.

**Rejoin.** The complete version and prompt are public here from the start:

```sh
uv run --locked python -m exercises.fixed.checkpoint rejoin 00-model
```

The command copies `fixed/checkpoints/00-model/{harness,prompts}` into the editable
directories. It first preserves **both** old directories under a unique
`exercises/runs/backups/` folder and prints that location. Earlier backups and
runs survive. Use the same command with `--exercises "path with spaces/exercises"`
to restore another workspace. Before moving to [01-read](../01-read/README.md),
swap drivers: driver B edits; driver A predicts what evidence the next request gains.
