# 03 · Keep evidence, resolve questions — minutes 25–45

**Say (25–28).** “A document is not an experiment. Keep the old bulletin so we
can explain the correction, but don't use its obsolete eligibility claim. Our
memory stores what sources say; the model still decides whether that evidence
answers the task.” Switch to case B. Driver B edits; driver A inspects evidence.
Keep the same program, tools, model settings and `prompts/system.md` from 02.

**Edit (28–35).** Inspect the readable `exercises/harness/memory.ts`. Each ledger
row links a verbatim source claim to its passage ID (the part before `:` is the
source ID) and half-open Unicode span `[start, end]`. `sources` holds dates,
experiment IDs, explicit correction links and conflict status. `experiments`
groups passage supports by experiment ID, not by
document count. `unresolved` lists referenced sources whose headers are still
unread; it is a work list, not proof that every substantive question is answered.
The synthesis reminder keeps unsupported conclusions open for the model to qualify.

After checkpoint 02's read/search registrations, add the import and create one
memory **inside `run`**, so it starts empty each time:

```ts
import { createMemory } from './memory.ts';
// Inside run(api), before constructing Agent:
const memory = createMemory();
```

Connect these two Agent options (already shown as comments in the starter):

```ts
afterToolCall: async ({ result }) => { memory.ingest(result.details); return undefined; },
transformContext: async messages => memory.context(messages),
```

The first retains evidence after a successful source read. The second constructs
the next Pi context from the unchanged system/task and the ledger. A read-only
batch is replaced by memory; a recent search/error batch keeps its complete
call/result pairs so discovery and failures remain actionable. Search snippets
are hints until read. No tool, prompt, arithmetic helper or reference lookup is
added. The completed copy below includes `memory.ts`, so it restores independently.
If you rejoined 02 and lost the starter file, copy the public file from this
checkpoint's `harness/` using your editor, or use the full rejoin command below.

**Run (35–39).** From the session folder after its pinned setup, save the earlier
02 harness **before editing**. These commands use the existing snapshot/launcher
on Linux, macOS and Windows; choose new names when rerunning:

```sh
uv run --locked python -m exercises.fixed.snapshot --name before-memory
# Make the two-hook edit above, or rejoin the complete checkpoint below.
uv run --locked python -m exercises.fixed.snapshot --name with-memory
uv run --locked python -m exercises.fixed.checkpoint run 03-memory --case b-compare --snapshot exercises/runs/versions/before-memory --offline
uv run --locked python -m exercises.fixed.checkpoint run 03-memory --case b-compare --snapshot exercises/runs/versions/with-memory --offline
uv run --locked python -m exercises.fixed.checkpoint compare --baseline exercises/runs/versions/before-memory --candidate exercises/runs/versions/with-memory --output exercises/runs/memory-ab
```

`run 03-memory` selects this block's read/search registry and public A/B script;
it runs the saved snapshot or current edits, **not** an automatic restoration.
Omit `--snapshot` to save and run current edits. Use `--case a-find` for A.
Comparison reruns A and B for both saved versions, copies their snapshots and
scripts, freezes prompts and shared settings, grades every attempt with the
existing evaluator, then applies its quality-first regression rule. Inspect
`comparison.md`, `before.md`, `after.md` and `shared.json` in the output directory.
An earlier passing A becoming a failure forces a revert even if B improves.

**Observe (39–43).** Open a B run's `memory-context.jsonl`. Each row links an
attempt ID to the exact line in `requests.jsonl` containing the actual outbound
context; its `memory` is extracted from that payload. Compare successive rows
around EV-S05 then EV-S06: what remains unresolved before the correction read,
which date and relationship makes the old claim superseded, and why do EV-S07,
EV-S08 and EV-S09 provide only **one** independent experiment? Where does the
second experiment enter? Find the shared-charger and 60-second constraints in
the final retained passages, then check the final typed claims and citations.
The ledger retains obsolete text with visible status rather than silently
deleting it. It follows explicit supersession, not “newest document always wins”.

Memory bounds: at most 64 entries, stored entry JSON at most 16 KiB and emitted
memory JSON at most 32 KiB (UTF-8). Overflow is visible as `omitted_entries` and a
capacity question; full reads remain in `tool-results.jsonl`. Reread narrower
spans before concluding from omitted evidence. Partial reads keep span IDs when
no passage heading is available and leave unknown metadata unknown. Context
also includes the fixed system/output contract, task and, for a search/error,
the last batch bounded by the supplied tool limits (4,096 code points/read,
eight 600-code-point search hits) and the 20-tool run cap. The launcher's unchanged
30,000-token admission bound covers the complete request plus reserved output;
`reservations.jsonl` records it. A ledger limit is not a model token estimate.

The public `transport-a.json` and `transport-b.json` are **synthetic scripted
evidence**, including worked final outputs. They exercise real Pi continuation,
tools, context construction, accounting and grading; they do not measure model
reasoning or live improvement. In the offline validation, A passes before and
after; B's uncompressed 02 context hits admission limits, while 03 completes.
This demonstrates this scripted workload's memory effect. Live compatibility,
autonomy and classroom timing require the separate pilot/rehearsal evidence.

**Rejoin (43–45).** The complete harness and unchanged prompt are public here:

```sh
uv run --locked python -m exercises.fixed.checkpoint rejoin 03-memory
uv run --locked python -m exercises.fixed.checkpoint run 03-memory --case a-find --offline
uv run --locked python -m exercises.fixed.checkpoint run 03-memory --case b-compare --offline
```

Rejoin backs up **both** editable directories under a unique `runs/backups/`
path before replacement. Explain the correction and experiment groups to the
other driver before moving to numerical checks. Offline behavioural validation:

```sh
uv run --locked pytest tests/labs/test_memory_checkpoint.py
npm run typecheck
```

The tests print the temporary A/B comparison and clean up its artifacts. They
also introduce a deliberately broken candidate to show that A regression is
reported; no prose answer is asserted.
