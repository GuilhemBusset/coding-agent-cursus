# 02 · Find the next source — remainder of minutes 10–25

**Say.** “Now let it find the next source. Search returns source IDs, snippets and
spans; the model chooses which source to read next. Our harness never names the
second source.” Follow [01-read](../01-read/README.md); driver A edits and driver B
traces where the chosen ID first appears.

**Edit.** In `exercises/harness/main.ts`, add one registration:

```ts
const tools: AgentTool[] = [api.researchTool('read'), api.researchTool('search')];
```

Keep `exercises/prompts/system.md` fixed. `search(query)` is the supplied local
lexical tool, not web search. The Agent loop and output code are unchanged.

**Run.** From the session folder with its pinned dependencies installed:

```sh
uv run --locked python -m exercises.fixed.checkpoint run 02-search --offline
```

**Observe.** In the printed output folder, inspect `trace.jsonl` in sequence:
read EV-S01 → search “Queue Repair” → read EV-S03 → answer. Inspect the search
hits in `tool-results.jsonl`, and the following `function_call_output` in
`requests.jsonl`. Find the assistant's EV-S03 read in `responses.jsonl`; the ID
comes from the model response, not a harness instruction. The final outbound
request includes both sources' evidence. The one new capability is **discovery
of another source from results**, beyond reading a known ID. Compare `report.md`,
`checkpoint-comparison.json`, `scorecard.json` and the public A reference. The
scripted partial answer is not a complete solution to A; inspect the remaining
requirements rather than treating successful tool calls as quality success.

This offline smoke is **synthetic scripted evidence**: the response fixture
chooses these actions, so it does not demonstrate live autonomy or a measured
quality gain. For an authorized live run, replace `--offline` with `--live` as
described in 00 and inspect the model's actual choices, including a correct
early answer or no tool use. Actual live checkpoint evidence belongs to pilot
#195. Keep synthetic runs separate from captured-live runs; both are labelled
in `config.json`. Do not add memory, arithmetic or recovery in this block.

**Rejoin.** The complete version and unchanged prompt are public here:

```sh
uv run --locked python -m exercises.fixed.checkpoint rejoin 02-search
uv run --locked python -m exercises.fixed.checkpoint run 02-search --offline
```

Both editable directories are backed up before replacement, and the command
prints the unique backup path under `runs/backups/`. This works without shell
copy commands on Linux, macOS and Windows. All versions retain the same
`harness/main.ts` entry point. Before minute 25, driver B explains the observed
source choice to driver A; rotate again when beginning the next teaching block.
