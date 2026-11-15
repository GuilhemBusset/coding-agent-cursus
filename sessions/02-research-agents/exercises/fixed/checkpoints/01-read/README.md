# 01 · Read one source — first part of minutes 10–25

**Say.** “Give it access to one source. Registering a tool lets Pi send the model's
requested source ID to the supplied reader, then send its evidence back to the
model.” Driver B types; driver A checks the request → result → next-request chain.
Finish [00-model](../00-model/README.md) first and retain its saved baseline.

**Edit.** In `exercises/harness/main.ts`, replace only the registration line:

```ts
const tools: AgentTool[] = [api.researchTool('read')];
```

Leave `exercises/prompts/system.md` unchanged. It already names EV-S01 as the
starting scope source. `read(source_id)` and its deterministic implementation
are supplied in `fixed/`; do not reimplement the reader or hard-code a source
sequence in the harness. Pi executes model-requested tools and continues.

**Run.** From the session folder, using the setup described in 00:

```sh
uv run --locked python -m exercises.fixed.checkpoint run 01-read --offline
```

**Observe.** Follow the printed `output` path under `exercises/runs/`.
`requests.jsonl` first declares only read. `trace.jsonl` shows a read of EV-S01;
`tool-results.jsonl` contains its exact bounded text and citation offsets. The
second provider request contains that tool result. Compare `report.md` and
`scorecard.json` with the saved baseline and public
`exercises/cases/a-find/reference.json`. The added capability is **evidence from
a known source**. It does not guarantee the full answer: the synthetic example
supports the method set and leaves other findings unresolved. The model can ask
for further known IDs, but there is no search interface yet.

The offline transport here is **synthetic**, with predetermined model decisions
and a partial answer; it proves wiring, not live autonomous source selection or
a measured improvement. The exact same program can run with `--live` after the
API setup and spending authorization described in 00. Keep those artifacts
separate; do not force a live failure. The prompt and fixed support stay the same.

**Rejoin.** Completed code and prompt are already public in this directory:

```sh
uv run --locked python -m exercises.fixed.checkpoint rejoin 01-read
uv run --locked python -m exercises.fixed.checkpoint run 01-read --offline
```

Rejoin saves both existing editable directories to the printed unique
`runs/backups/` location before replacing either. Keep the backup if you want to
return to your edit. Swap drivers again for [02-search](../02-search/README.md):
driver A edits; driver B predicts where the next source ID will come from.
