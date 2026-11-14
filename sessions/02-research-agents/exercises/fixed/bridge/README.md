# Fixed evidence tools (offline)

Students can inspect `bridge.ts`, `dispatch.py`, `../tools/corpus.py`,
`../tools/research.py` and the reused `../corpus/audit.py`. No provider call is
needed. From the session directory, after the
[documented session setup](../../../README.md#standalone-session) installs the
pinned runtimes and locked packages:

```console
mise exec -- uv run --locked node exercises/fixed/bridge/inspect.ts --case exercises/cases/c-audit
```

This prints the actual model-facing JSON schemas, descriptions, limits and a real
search result. To register with Pi, import `createResearchTools` from `bridge.ts`
and pass `{ caseRoot, runId }`; supply its returned registrations to the Agent's
`tools`. `caseRoot` is the trusted path to one base case or published variant,
containing `corpus.json` and `sources/`. Use `mise exec --` to select the session's
pinned Node/npm, and run Node through `uv run --locked` so `python` resolves to
the session environment. A trusted caller may instead pass an
absolute `python` executable path. Arguments are sent as UTF-8 JSON over stdin;
Python is spawned with an argument array and `shell: false`. Neither roots nor
executables are exposed in the research-tool schemas. There is no Bash or
PowerShell-dependent student code.

## Interface and evidence

- `read({ source_id, start?, end? })`: exact normalized text and its source span.
  Omit both offsets for the first min(4096, source length) code points. Explicit
  offsets must be ordered, within the source and at most 4096 code points apart.
  `audit.passage_ids` lists overlapping manifest passages; partial source reads
  report `truncated: true`. CSV reading returns textual code-point spans;
  table calculations cite data rows separately.
- `search({ query, limit? })`: query 1–256 code points with at least one word;
  limit 1–8, default 5. Search the manifest's validated passage text using the
  count of distinct overlapping case-folded Unicode words. Sort by descending
  score, source ID, then passage offset. No stemming or semantic inference.
  Snippets contain at most 600 code points centered near the first matching
  word; exact snippet spans and parent passage IDs/spans are returned. CSVs
  without manifest passages are read or calculated, not searched as prose.
  `audit.total_hits`, per-hit `truncated`, and overall `truncated` distinguish
  omitted hits and shortened passages. A miss is a successful empty list.
- `check_table({ source_id, method_left, method_right,
  metric: "cost", unit, feasible_only: true, pair_key: "pair_id", pair_ids })`:
  the only operation is feasible paired cost reduction. Supply the CSV's unit
  (`fictional-cost-units`), two distinct methods present in the CSV, and 1–100
  distinct known pair IDs. The left method is the baseline named by the protocol
  source (audit-a in the base case; methods are renamed in variants). Pair identical
  instance/run identities with exactly one row per method and both feasible.
  Duplicate/ambiguous rows fail; incomplete or infeasible pairs are excluded.
  Unrequested rows are excluded with their own reason. At least one feasible
  complete pair and a positive baseline total are required.

Table results include all numeric pair inputs, source ID, unit, positional row
citations, excluded positions and means. Supplemental `audit` metadata supplies
logical row IDs, both method execution IDs, instance/run identities, excluded
logical IDs/reasons, totals, denominator and percentage. The formula is
`relative_reduction = (sum_left - sum_right) / sum_left`, with
`reduction_percent = 100 * relative_reduction`. Means divide each total by the
same feasible-pair count. The v1 pair's single `experiment_id` identifies the
left execution; both executions are explicit in `audit.pairs`. The bridge checks
response identities and the ratio/percentage/unit consistency before returning.
No operation evaluates model-supplied expressions or code.

Normalization is UTF-8, universal newlines to LF, Unicode NFC. Passage offsets
are zero-based half-open Unicode code points, not JavaScript UTF-16 indices.
Row spans are one-based half-open CSV data rows, excluding the header.

## Protocol, limits and errors

One process handles one JSON request `{tool, arguments, run_id, tool_call_id}`.
A successful protocol exchange returns `{bridge_version: "1.0", invocation,
result, audit}`. `invocation` is the explicit bounded v1 tool input after defaults
are applied; `result` preserves the closed `tool-result.v1` contract. For rejected
arguments the invocation retains the rejected input for diagnostics and is not
claimed to be a valid v1 input. Both artifacts retain run/call/tool identities.
Pi receives this full wrapper as both JSON text `content` and structured
`details`, so audit metadata is available to the model as well as the caller.

Typed tool failures use `result.status: "error"`, `data: null` and
`error: {code, retryable: false}`. `not_found` means a syntactically valid unknown
source ID. `invalid_input` covers unsupported/malformed arguments, unknown pairs,
invalid spans, calculation failures and malformed evidence. `audit.message`
explains the failure. Invalid envelopes, unknown tools or bundle-load failures
return a protocol-level `{bridge_error: {code, retryable: false}}`; the TypeScript
caller raises `BridgeError`, and Pi receives structured `details.error` with
`isError: true`. Transport failures similarly use `service_error`, cancellation
uses `cancelled`, and the 10-second default deadline uses `timeout`. Every Pi
error marks `isError: true`; none requires parsing an exception string.

Requests are at most 16 KiB and responses at most 128 KiB of UTF-8 JSON (plus a
trailing newline). Oversized inputs/results fail instead of silently discarding
JSON. Bundle limits: 100 sources, 1 MB manifest, 1 MB per source, 1000 CSV rows;
identifiers are at most 128 ASCII identifier characters. These limits bound this
small dossier implementation, not a general search service.

Runtime data access is restricted to `corpus.json` and manifest-listed `.md` or
`.csv` files directly under `sources/`, with resolved containment checks rejecting
symlink escapes. Read/search use source text, and calculations use CSV evidence.
No `case.json`, references, rubric, worked answers, provenance maps or grader is
loaded. No filesystem path, command, network retrieval or answer lookup is a
research-model tool. This is tool scoping, not an OS sandbox: student code and
all public answers remain inspectable.

Portability is implemented with standard Python and Node APIs. Offline Linux
subprocess tests include Unicode, newlines and paths with spaces; those tests do
not claim native macOS or Windows execution evidence.
