# Public faults and offline replay

Start with the [announced inventory](../config/public/manifest.json), its
[11 fault specifications](../config/public/faults/), and
[expected outcomes](expected.json). These are public before class. The earlier
specification notes describe the publication stage; the executable consumer is
now [fixed/faults](../faults/__main__.py). Each saved run under [faults/](faults/)
contains its selected schedule in `config.json → fault`, activation events in
`trace.jsonl`, synthetic Responses transport in `transport.json`, scorecard and
`provenance.json`. None is a live recording. Counts and token values are scripted,
illustrative test inputs, never measurements of API price or performance.

From the session directory, after the [locked setup](../../../../../setup/README.md)
(use the repository's `setup/README.md` if viewing an exported session):

```text
mise exec -- uv run --locked python -m exercises.fixed.faults --scenario transient-read --out exercises/runs/fault-read-01
mise exec -- uv run --locked python -m exercises.fixed.replay --run exercises/fixed/fixtures/faults/transient-read --out exercises/runs/replay-read-01
mise exec -- uv run --locked python -m exercises.fixed.replay --run exercises/fixed/fixtures/faults/tool-budget --out exercises/runs/replay-budget-01
mise exec -- uv run --locked pytest tests/labs/test_fault_replay.py
```

Choose a new `--out` each time; an existing directory is refused. Once dependencies
are installed, these commands need no credentials or network. Every scenario name
in the manifest is accepted by `--scenario`. Injection executes the real Pi adapter,
tool dispatch boundary, trace validator and grader. Replay only validates and
regrades saved events, so needs Python and locked dependencies but no model/Node
process. Tests deny network access and child processes during replay.

The completed [bounded read recovery example](../faults/recovery.ts) executes one
retry on a retryable error and retains the failed invocation and `retry_of` link.
Permanent absence gets no retry. Repeated retrieval stops after the third identical
result adds no new evidence. Malformed arguments are counted but rejected before
source access; raw malformed output remains in `candidate-output.json`.
The generated harness in `faults/__main__.py` also demonstrates no-progress and
budget stopping. It is supplied support; student edits stay in `harness/`.

Budget prefixes are actual synthetic dispatches: 12 model attempts, 20 tools, or
one 30,000-token scripted response followed by a refused admission. Limits stay
12/20/30,000. The token example explicitly uses 8,192 maximum output tokens and
4,534 padding characters to fill the conservative request reservation under this
contract. Timeout cancels each 1,000 ms attempt; HTTP 429 waits 10 ms before its
one retry. These two announced recovery attempts may retain unknown usage; no
ordinary subsequent research is admitted with unknown usage. Absent usage stops
at `token_budget` and keeps all usage null.

Replay writes `config.json`, `trace.jsonl`, `accounting.json`, `policy.json`,
`claims.json`, `report.json`, `report.md`, `scorecard.json`, `grading.json`,
`peer-review.md`, `efficiency.json`, and `provenance.json`. It preserves the exact
original `source-config.json`, `source-trace.jsonl` and `source-provenance.json`.
New run/workspace envelope IDs distinguish inspection from the source run;
request/attempt/tool/event IDs and failure/retry counts remain intact. The source
directory is untouched. All replay configs, scorecards and CLI summaries say
`evidence_kind=replay`, with `replay_of` and original provenance. There is no
option to relabel replay as live; saved-version live comparisons reject it.

The source envelope covers configuration, policy, trace, typed output, report and
scorecard digests, plus selected case files. Invalid JSON, missing termination,
changed bytes or mismatched hashes reject replay before writing a destination.
Digests detect damage since sealing; they do not authenticate a capture's origin.
Regrading uses the installed public evaluator, so later evaluator revisions can
change grades while the retained source scorecard remains hash-identified.

All supplied recovery examples with partial answers fail quality honestly. The
absent-usage case scripts the public C example specified by its fault contract;
it passes typed quality while having **unknown efficiency**. Neither a quality
pass nor a replay establishes live autonomous research. Peer prose review remains
pending. See [capture instructions](../faults/CAPTURE.md) and the instructor's
[outage/rejoin runbook](../../../cursus/demos/replay/README.md).
