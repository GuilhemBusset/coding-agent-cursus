# Recorded agent runs · replay catalog

`agent-demos.json` is the catalog that the agent-loop replay widget,
[`cursus/labs/agent-loop.html`](../../labs/agent-loop.html), plays. It is generated, never edited by
hand: [`normalize_runs.py`](normalize_runs.py) builds it from the Act III demo recordings in
[`cursus/demos/agent/recorded/`](../../demos/agent/README.md) and copies the same bytes into the
page's inline `<script type="application/json" id="agent-runs" data-sha256="…">` block. The page
reads nothing at runtime, so it works over `file://` with no server and no network.

From `sessions/01-fundamentals`, after any `agent_demo.py run … --record`:

```sh
uv run cursus/fixtures/runs/normalize_runs.py           # rewrite the catalog and the page's copy
uv run cursus/fixtures/runs/normalize_runs.py --check   # write nothing; exit 1 if either is stale
```

The script uses only the Python standard library, opens no socket and finds its paths from its
own location, so it runs the same from any directory. It changes nothing in the page except that
one block and its `data-sha256`.

## Inputs and how each stream is matched

One catalog run per raw stream `recorded/<stem>.jsonl`; the run's `id` is the stem. Its parent
rehearsal is the one `recorded/<rehearsal>.meta.json` whose stem equals the stream's stem (the
loop) or is its prefix followed by `-<arm>` (plan: `direct`, `plan`, `build`; bomb: `without`,
`with`, `with-tool-search-off`). The script stops with a message on a stream with no parent
or with several, on an arm the meta does not declare, on an armed rehearsal's stream with no arm,
and on a meta or a declared arm that no stream uses.

## Schema 1

```text
{ "schema": 1,
  "runs": [ {
    "id", "demo" (loop | plan | bomb), "cli" (claude | codex), "rehearsal", "run", "arm" (or null),
    "meta": { "cli", "cli_version", "model", "model_source", "effort",
              "started_utc", "ended_utc", "exit_code" },
    "usage":    the stream's last usage event, verbatim (null if none),
    "captures": { "before", "after" } for bomb runs, else null,
    "per_step": { "context_occupancy": null, "timestamp": null, "usage": null },
    "steps": [ { "type" (thought | tool_call | tool_result | message), "text", "chars",
                 "truncated", "tool"?, "input"?, "exit_code"?, "is_error"? } ] } ] }
```

- **meta.** `cli`, `cli_version`, `model`, `model_source` and `effort` come from the rehearsal's
  meta. The times and the exit code come from the arm's own block (from the meta's top level for
  the loop, which has no arms), else from the stream's final `result` or `turn.completed` event,
  else `null`. They are never copied from the rehearsal's totals.
- **usage.** The `usage` object of the last `result` (Claude Code) or `turn.completed` (Codex)
  event, unchanged. Nothing is summed or derived, so cached input is never counted twice.
- **captures.** For bomb runs, the text of `<rehearsal>-context-{before,after}.txt` (Claude Code)
  or `<rehearsal>-status-{before,after}.txt` (Codex), byte for byte. Every arm of a rehearsal
  shares them.
- **per_step.** Neither CLI's stream records per-step timestamps, per-step usage or context
  occupancy, so these are `null` and the page says "not recorded". Nothing is invented.
- **steps**, in stream order.
  - `claude -p --output-format stream-json --verbose`: assistant `thinking` → `thought`,
    `text` → `message`, `tool_use` → `tool_call` (`tool` is the name, `input` the input as
    sent), and the user's `tool_result` → `tool_result` (`tool` from the matching call,
    `is_error`, `exit_code` when the stream gives one). `system`, rate-limit and `result` events
    give no step.
  - `codex exec --json`: completed `reasoning` → `thought`, `agent_message` → `message`. A
    started `command_execution`, `file_change` or `mcp_tool_call` → `tool_call` (`tool` is the
    item type, `input` its `command`, `changes`, or `server`, `tool` and `arguments`). The
    matching completed item → `tool_result` (`aggregated_output` or the MCP result's text,
    `exit_code`, and `is_error` when the item failed or exited non-zero).
  - A `tool_call`'s `text` is what the page shows: the command, or the input as indented JSON.
  - Texts longer than 1,200 characters keep their first 1,200 characters, with
    `"truncated": true`. `chars` is always the full length. The raw stream keeps the rest.

Serialization: UTF-8, keys sorted, one-space indent, a final newline. Every `<` is written as
`\u003c`, so no text can close the page's script block. An `@` directly after a JSON control
escape is written as `\u0040` (for example `\n@pytest.fixture`, a decorator at the start of a
line), so a privacy scan of the file does not mistake `n@pytest.fixture` for an e-mail address.
Both are standard JSON escapes and decode to the same text.
