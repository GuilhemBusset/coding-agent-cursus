# Session 2 research contracts — v1.0

These interfaces freeze the boundary for the later corpus, tools, Pi adapter,
launcher and evaluator. They follow the [locked plan](../../../../docs/session-02/README.md).
They define data and command behaviour; the commands, corpus and grading algorithm
are delivered by downstream issues. No model call is needed to validate this package.

All names, findings, model names, revision names and hashes in the examples are
**illustrative**. They are not the public EV dossier, a compatible model selection,
a real rating bundle, pilot evidence or a measured research result. In particular,
`illustrative: true` bundles must be rejected for actual rating. The later bundle
will pin the public corpus and evaluator after they exist; there is no hidden split.

## Files, versions and language boundary

Every artifact has `schema_version: "1.0"`. Schema filenames carry their major
version; `$id` values and `$ref` targets are local filenames. Unsupported versions
fail rather than being coerced. Breaking meaning or required fields needs a new
major filename and an explicit migration. All objects are closed to extra fields.
The schemas use JSON Schema draft 2020-12, with common types in
[common.v1.schema.json](schemas/common.v1.schema.json).

| Artifact | Schema in `schemas/` | Producer → consumer |
| --- | --- | --- |
| Question, context, tool registration and reference location | `case.v1.schema.json` | Public case author → launcher |
| Per-case `reference.json` | `reference.v1.schema.json` | Public case author → evaluator after research |
| `claims.json` | `claims.v1.schema.json` | Research model, enveloped by launcher → evaluator |
| `report.json` metadata and `report.md` anchors | `report.v1.schema.json` | Research model, enveloped by launcher → evaluator/peer |
| Tool invocation arguments | `tool-input.v1.schema.json` | Pi TypeScript bridge → Python tools |
| Evidence, calculations or typed tool error | `tool-result.v1.schema.json` | Python tools → Pi TypeScript bridge |
| `config.json` | `run-config.v1.schema.json` | Fixed Python launcher → adapter, harness, evaluator |
| Immutable baseline/candidate manifest | `snapshot.v1.schema.json` | Fixed launcher → launcher/comparison |
| One line of `trace.jsonl` | `trace-event.v1.schema.json` | Fixed adapter/tool boundary → replay/evaluator |
| Per-run `scorecard.json` | `scorecard.v1.schema.json` | Fixed evaluator → comparison |
| Public gates, budgets, seed/trial schedule | `policy.v1.schema.json` | Instructor → launcher/evaluator |

Python owns the launcher, corpus utilities and evaluation; TypeScript owns the
single Pi agent and its orchestration. Exchange UTF-8 JSON values, with one complete
JSON object per line on the tool process stdin/stdout. Diagnostics go to stderr;
stdout contains only protocol objects. Reject malformed JSON, nonfinite numbers,
wrong versions, unknown tools, extra fields and mismatched identities. Preserve
array order, distinguish `null` from zero, and use integers within JavaScript's
safe-integer range at both boundaries. Do not send Python objects, pickle, shell
commands, arbitrary paths or TypeScript class instances through the protocol.
A tool error is a typed result, not an exception string or provider response dump.

The launcher assigns run IDs; the adapter assigns request/attempt IDs and Pi's
boundary assigns invocation IDs. Model tool arguments correspond only to
`arguments` in the input envelope: the bridge supplies the trusted outer IDs.
For model output, the model writes claims and report content; the launcher adds
identity/path metadata and rejects any conflicting model-supplied identity.
The JSON Schemas are usable from either language. The standard-library
[validator](schemas/validate.py) deliberately supports only their small vocabulary;
unknown schema keywords fail explicitly. It validates shape, ordering and
relationships, not source truth or prose entailment. It is not a general schema
framework, corpus checker, grader or CLI implementation.

[positive.json](schemas/examples/positive.json) is a named collection of
`{name, schema, value}` examples, covering every artifact schema. Shape-valid
unsupported/unknown claims and failed runs are positive interface examples, not
passing answers. [negative.json](schemas/examples/negative.json) contains full
rejected artifacts with a diagnostic category. The tests validate every entry,
the configuration files, each A/B/C JSONL trace and its Markdown report, and the
linked [failed run](schemas/examples/failed-run.json). The `error` field in the
negative collection describes an interface failure; it is not an expected research
answer. Collections themselves are fixture packaging, not runtime artifacts.

## Assertions, references and support

Facts and claims share an assertion: `subject`, `predicate`, `type`, `value`, `unit`.
Subjects and predicates are stable domain identifiers. Types are `string`,
`boolean`, `string_set` or `number`. Set order carries no meaning. Non-numeric
assertions have `unit: null`; numeric assertions always state a unit and a tolerance
with finite, nonnegative `absolute` and `relative` terms. Zero tolerances mean exact
comparison. Numerical matching uses
`abs(observed - expected) <= max(absolute, relative * abs(expected))`, after
matching subject/predicate/type/unit. Units must agree; silent conversion is forbidden.
Tolerance belongs to the reference; a claim's proposed tolerance cannot loosen it.

Each reference fact has `fact_id`, `required`, `decisive`, accepted evidence,
`experiment_ids` and `supersedes_fact_ids`. Decisive implies required. Historical
superseded fact IDs identify earlier public reference revisions; they do not add
an obligation to satisfy an obsolete assertion. A reference uses
`evidence_policy: required` with one or more accepted spans for affirmative facts.
`absence` with no spans represents an evaluator-reviewed missing-evidence fact,
not a fabricated citation to a nonexistent source. The evaluator checks the public
corpus inventory for that absence. `required_uncertainty` identifies the subject,
predicate and reason the report must explicitly qualify or withhold. This permits
correct abstention to satisfy an absence requirement.

A passage span is `{source_id, kind: "passage", start, end}`. Offsets are zero-based
Unicode code points into the decoded, newline-normalized (`CRLF`/`CR` → `LF`)
source text, start inclusive and end exclusive. TypeScript must index code points,
not UTF-16 code units. A row span has `kind: "rows"`, one-based **data** row indexes
(header excluded), the same half-open convention, and named `columns`. Spans are
nonempty, ordered and bounded by the pinned source. `source_id` resolves only
inside the run's corpus revision; it is never a URL or arbitrary file path.
Evidence matching accepts a cited subspan of an accepted passage/row range when it
contains the assertion's supporting evidence. A broad range or matching source ID
alone is insufficient. Source bounds, quoted content and entailment belong to the
later tool/evaluator; these fixtures demonstrate their representation.

`corrections` link a new source to the superseded source and affected facts. A
corrected assertion must use the corrected evidence, while the obsolete source
can still be cited to explain the change. `experiments` associate one independent
experiment ID with every source reporting it; two documents with the same ID count
once. Claims carry the experiment IDs they actually use and can explicitly
supersede earlier claim IDs retained in the ledger. IDs never replace assertion or
span checking. Unsupported superseded claims remain auditable; any factual claim
still in the final output must pass the factual support gate.

Claims explicitly distinguish `factual`, `decision` and `uncertainty`, and
`supported`, `unsupported` and `unknown`. Supported factual/decision claims need
spans. Unsupported claims remain representable for failed outputs; `unknown` has
no asserted supporting span. `reference_fact_ids` are optional matching hints
(the array can be empty). Matching a fact ID is **not** evidence of correctness,
entailment or adequate citation. The evaluator compares typed values, requirements,
accepted source spans, correction/experiment identities and required uncertainty.
A decision needs evidence for its premises and scope, not just its conclusion ID.

`report.json` maps every final claim ID to one unique Markdown anchor, for example
`<a id="claim-time-limit"></a>`. Each anchor appears exactly once immediately before
the prose asserting or qualifying that claim. A claim can use multiple sentences;
an anchor does not certify their meaning. Factual statements in the report must
have corresponding structured claims, including extra facts the model volunteers.
Peer review checks this coverage and prose entailment separately from code grading.
No fixed phrasing or Markdown sentence comparison is part of the contract.

### Expressiveness examples (not the future answer key)

- A identifies the set `{GridMILP, SlotSearch}` plus separate assumptions for each:
  known demand, half-hour slots or a fixed charger count. Set membership and typed
  assumption claims allow equivalent phrasing and reordered method lists.
- B represents both shared-charger feasibility and a numerical solve time of 42 s
  against the question's 60 s constraint. The correction withdraws GridMILP's
  eligibility. `corrected-results` and `summary` share `exp-1`; repeating the summary
  supplies no second independent experiment. The conditional recommendation cites
  the corrected premises. `superseded-claims` demonstrates a retained obsolete claim.
- C's `check-result` pairs data rows 1/2 and 3/4 by `p1`/`p2`, includes feasibility,
  cost units and experiment IDs, and excludes rows 5/6. The arithmetic is
  `(mean(left) - mean(right)) / mean(left) = (100 - 80) / 100 = 0.2`.
  Only specified pairs with **both** members feasible enter either mean; exclude
  an entire pair if either member is infeasible or missing. No cross-pair cherry
  picking. A zero left mean yields a typed `invalid_input` result rather than an
  invented percentage. The reference records missing uncertain-demand evidence;
  the report explicitly withholds that superiority claim. A measured reduction
  and an unsupported generalisation are separate assertions.

`read` returns a bounded passage; `search` returns bounded passage hits with spans;
`check_table` returns selected pairs, excluded rows, means, units, reduction and
row citations. Error codes include `not_found`, `invalid_input`, `timeout`,
`service_error`, `cancelled`, and `budget_exhausted`, with an explicit retryability
flag. Tool limits and source-bound checks are implemented in the tools issue.
The checker recomputes from corpus rows; it never reads `reference.json`.

## Trace identity, accounting and termination

A `run_id` identifies one version/case/variant/trial execution. Every run gets a
fresh workspace ID. A `request_id` identifies a logical model request; each actual
outbound dispatch, including a retry, gets a different `attempt_id`. The retry
links to a previous failed attempt of the **same** request with `retry_of`.
Each tool dispatch gets a unique `tool_call_id`, including failed and retried tool
invocations. Tool retries link to a prior failed invocation with the same tool and
arguments. Tools also identify the successful model attempt that requested them.
IDs are unique within their run; external references always include `run_id`.

Trace lines have unique `event_id`, contiguous zero-based `sequence`, and monotonic
`elapsed_ms` from run launch. `duration_ms` measures each attempt/invocation and
includes waiting; durations may overlap and are not summed to derive elapsed time.
One `model_attempt` summary is emitted per dispatched outbound attempt, including
partial stream failures and cancellation, with its own status, sanitized error and
usage. One `tool_invocation` summary retains validated input and result. Events are
emitted on finalization; the fixed boundary retains in-flight records for failure
recovery and finalizes partial attempts, never silently dropping them on an error.
An unfinalized crash trace is retained as incomplete evidence; it cannot be treated
as a completed valid trace or pass a replay validation.

A human edit, steer or resume during a run emits an `intervention`; the sole final
`run_end` repeats whether any intervention occurred. Editing the next saved version
between runs is not intervention in a run. No trace event may follow `run_end`.
The end reason is one of `completed`, `no_progress`, `model_budget`, `tool_budget`,
`token_budget`, `invalid_output`, `service_error`. `completed` means a final artifact
was produced, not that it passed grading. A run ending for another reason may have
usable final artifacts, but must still satisfy every quality gate to count as a
success. Deterministic no-progress rules and retry policies are saved in the hashed
harness; service errors never imply success. Stop at the first terminal condition
observed by the launcher, retain the partial output and all dispatched attempts.

Usage is normalized at the supplied adapter boundary:

- `input_tokens` includes ordinary input **and** cache-read/cache-write input.
- `output_tokens` includes ordinary output **and** reasoning output.
- `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens` are informational
  subsets. Cache subsets are disjoint; their sum cannot exceed input. Reasoning
  cannot exceed output. Never add these subsets again to input/output totals.
- Normalize provider semantics before writing events. If a provider reports a
  subset-excluding total, include its subsets exactly once. A genuinely unknown
  count is `null`, never zero, estimated text length or the configured maximum.
- Every usage object requires `status`. `complete` means every count is known;
  `partial` means some known and some unknown; `unknown` means all counts are null.
  A documented known absence of caching/reasoning is zero. Unreported is unknown.
- Sum each field across **all** model attempts, including failed/cancelled dispatches
  and retries. Any unknown contributor makes that field's aggregate null. Total
  tokens is aggregate input + aggregate output; if either is null the total is null.
  Unknown subset detail does not erase independently known normalized input/output.
  Tool checker work itself consumes no model tokens, but tool results sent back to
  the model are counted in the next model input.

The provisional per-run caps in [policy.v1.json](config/policy.v1.json) are **12
outbound model attempts, 20 tool invocations and 30,000 normalized input-plus-output
tokens**. Retries consume caps. Before dispatch, the launcher admits only work that
fits known remaining budget and bounds model output; it cancels at a reached cap.
Unknown usage cannot authorize unlimited further calls: stop further paid dispatch
and record `service_error` for unavailable accounting (or `token_budget` if a known
cap has already been reached). Keep any measured overshoot; a cap cannot justify
truncating observed usage. These are proposed caps, pending live pilot calibration;
`provisional`/`pending_live_pilot` must not be presented as classroom validation.

## Configuration, public bundles and model inputs

Saved configuration fixes provider, pinned model identity, supported settings,
endpoint **alias**, budgets, seed/trial schedule, snapshot, corpus and evaluator.
The example model pin is a placeholder; the adapter issue selects the real OpenAI
snapshot through a compatibility check. Unsupported settings fail before dispatch;
`null` settings explicitly record unsupported/not requested settings, not defaults
chosen silently. The public variant seed generates task variants, independently of
an optional model sampling seed; a variant seed promises no deterministic model
sampling. Compare versions only with identical saved model/settings, endpoint alias,
corpus, evaluator, policy, schedule and public bundle.

Resolve alias `course-openai` through environment configuration at launch (for
example `S2_ENDPOINT_COURSE_OPENAI` and `OPENAI_API_KEY`). Provider routing details,
URLs, query parameters, authorization headers and credentials never enter saved
configuration or traces. Reject unknown aliases; strip secret-bearing raw provider
errors at the boundary. Settings and schemas have no arbitrary provider dictionary
that could carry secrets. Never serialize the environment. Students can configure a
different provider and alias without changing these interfaces; that requires the
same smoke checks and budget recalibration later.

All SHA-256 fields use lowercase hex. Hash **bytes**, not language object reprs.
The publisher writes immutable UTF-8 manifests once; consumers hash those exact
bytes rather than independently serializing objects. File-set manifests enumerate
sorted session-relative POSIX paths and file-content SHA-256 digests. Aggregate
harness/prompt/corpus/evaluator hashes are SHA-256 of their corresponding manifest
bytes. `hashes.model` hashes the UTF-8 bytes `provider + "\n" + model + "\n"`;
`hashes.settings` hashes the saved settings JSON file bytes; `policy_sha256` hashes
the saved policy file bytes. Record these files beside the run config for replay.

The rating-bundle descriptor records a public immutable revision and SHA-256 of
its exported file manifest (public tasks, sources, references, evaluator and fixed
support, each with path and byte hash). `hashes.rating_bundle` repeats that digest.
The launcher retrieves/verifies the pinned copy, verifies each member before use,
and records its revision/digest in every config; local student edits cannot replace
rating support. A digest or missing bundle mismatch fails before research, never
falls back to local answer keys. References/evaluator remain publicly inspectable.
Illustrative fixture hashes intentionally do not certify real content; relationship
tests check consistent identities, not external artifacts that do not yet exist.

Snapshots enumerate harness and prompt files with byte hashes, aggregate hashes,
an immutable ID, role (`baseline`/`candidate`) and `immutable: true`. Preserve both
manifests and copied bytes; never update an existing snapshot in place. Each run
records its snapshot ID and those hashes. Comparison verifies them before launching;
a changed byte requires a new snapshot ID. Harness-only experiments keep prompt
hashes fixed; prompt experiments keep harness hashes fixed. Identity checking is
not a claim of an OS sandbox for student code.

For **each trial**, launch a fresh temporary workspace without prior reports,
conversation history, claims memory or scores. `workspace.fresh: true` attests this
launcher action; unique `workspace_id` and `supplied_inputs` record what it received.
The model-visible envelope consists of exactly:

1. The case question and local context (including the local P01 summary), and the
   saved student prompt/system instructions.
2. Definitions for the registered `read`, `search`, `check_table` corpus-ID tools.
   Corpus content enters through these tool results; checker results include
   paired-row evidence and arithmetic. Only registered tools are callable.
3. The output contract: typed claims, explicit uncertainty, and report anchors.
   Prior messages and tool results from **this** run can be retained by the harness.

The launcher retains the complete case contract but omits `reference_path` from
model messages. References, accepted facts/spans, rubric, evaluator code, grading
assertions, pass/fail results and scorecards are **evaluator-only until after the
run**, despite being public in the repository. They are not tool results and are
not automatically injected into context. The research table checker is distinct
from the grader. Trial seed/variant select public inputs; fresh workspaces are a
controlled experimental boundary, not secret tests or access prevention. A candidate
that manually injects evaluator material violates the documented input contract;
that behaviour must not be certified as ordinary research evidence.

## Common CLI contract (to be implemented)

Run from the session directory using the Python entry point
`uv run python exercises/fixed/research.py <command>`. Paths below are relative to
that directory; commands must work with spaces and on Linux, macOS and Windows.
This issue defines the interface; it does not supply `research.py`.

| Command and required arguments | Inputs and outputs |
| --- | --- |
| `snapshot --role baseline\|candidate --harness exercises/harness --prompt exercises/prompts --out exercises/runs/<snapshot>` | Copies selected files, writes `snapshot.json` plus immutable harness/prompt manifests and bytes. Reject an existing destination; source edits afterwards cannot change it. |
| `run --snapshot <snapshot-dir> --config <run-config.json> --case A\|B\|C --policy <policy.json> --mode class\|submission --trial N --out <run-dir>` | Selects variant/seed from public schedule, resolves the pinned bundle and explicit environment provider/model settings, records complete `config.json`, then starts a fresh workspace with the verified snapshot. Writes `claims.json`, `report.md`, `report.json`, `trace.jsonl`, settings/hash manifests and failure details. It never supplies grades to the model. |
| `grade --run <run-dir> --policy <policy.json> --bundle <verified-bundle-dir>` | After research has stopped, validates identities/hashes, loads that bundle's reference/evaluator and writes `scorecard.json`. Does not invoke a model or alter research evidence. |
| `compare --baseline <snapshot-dir> --candidate <snapshot-dir> --config <run-config.json> --policy <policy.json> --mode class\|submission --out <comparison-dir>` | Uses the config as the shared provider/settings/bundle template (new run/workspace IDs per trial), runs and grades both saved versions on the exact same scheduled variants/seeds/trials. Writes version/case aggregates and before/after scorecards, failed assertion IDs and linked run IDs. |
| `replay --run <recorded-run-dir> --out <new-run-dir>` | Validates recorded identities, hashes, event sequence and accounting, reconstructs offline without paid calls and writes replay artifacts with a new run/workspace ID, `evidence_kind: replay`, `replay_of` original ID. Retains the original trace separately and remaps the replay trace's envelope IDs consistently. Never relabels replay as captured live. |

`run` obtains provider/model/supported settings from the explicitly selected public
run-config template; no global Pi config is consulted. New run/trial/workspace fields replace
the template identities, and all effective settings are saved. `compare` similarly
replaces template case/variant/trial/seed values from the schedule. All rating commands
reject illustrative bundles; examples here explain the shapes, not runnable rating.

All commands validate inputs before model dispatch. Exit codes: `0` command
completed with valid artifacts (a low-quality graded answer may still be valid),
`2` invalid arguments/contracts/version/identity/hash or immutable-destination
collision, `3` interrupted execution/service/budget/output failure with retained
partial evidence. No retry may silently change configuration. `grade`/`compare`
record low quality and zero success explicitly rather than making incomplete
research look successful. Every already-dispatched attempt survives a nonzero exit.
No command overwrites earlier evidence directories.

[policy.v1.json](config/policy.v1.json) publishes one announced `public-1` variant
per A/B/C for class, and three trials per case per saved version for submission.
The exact public seeds are in its schedule, announced before building. Each public per-case seed fixes the variant across the three independent submission
trials; model sampling can still vary. Baseline and candidate use the same schedule. The
manifest examples under `config/` freeze interface shapes only. Actual public
variant generation and the pinned runnable rating bundle are supplied downstream.

## Gates, score sources and comparison

The provisional quality pass is the conjunction of all decisive requirements,
required fact coverage ≥ 0.8, valid support spans for **every** factual claim,
no unsupported decision, required uncertainty, valid output, and no intervention.
Unsupported/unknown factual assertions cannot evade the citation gate by omitting
spans; explicit justified uncertainty can pass its own requirement. A case's absence
fact can be satisfied by correctly withholding a claim. Supported decision claims
still require the evaluator to check their premises. Extra unsupported factual
claims fail even when every required fact was supplied.

Code emits individual grading assertions with stable IDs, categories, target IDs
and passed flags. `required_fact` assertions target one required reference fact
each. Other categories cover the decisive fact IDs, factual claim IDs, decision
claim IDs, uncertainty requirement IDs and case ID (output). A category with no
applicable targets has one vacuously passing assertion targeting the case ID.
`failed_assertion_ids` is exactly the list of failed grading assertion IDs. These
are supplied by the future evaluator, not by the candidate. Validation checks their
internal consistency; it cannot establish the truth of supplied assertions.

Every required scorecard field has the following source:

| Scorecard fields | Authoritative source / derivation |
| --- | --- |
| `schema_version` | Fixed evaluator's output interface version |
| `run_id`, `case_id`, `variant_id`, `hashes`, `policy_sha256`, `evidence_kind` | Validated launcher config and pinned bundle; identities must match every run artifact |
| `grading_assertions`, `failed_assertion_ids` | Fixed evaluator's typed-fact, decisive, citation, decision, uncertainty and output assertions; failed IDs are exactly false assertions |
| `required_facts_total`, `required_facts_met`, `required_fact_coverage` | Required reference facts and their individual `required_fact` assertions; met / total |
| `decisive_pass` | All decisive assertions pass, including both B constraints, correction and independent-evidence accounting where decisive |
| `all_factual_spans_valid` | All citation assertions pass for every factual claim, checking accepted evidence, source bounds and support, not just the existence of an anchor |
| `no_unsupported_decision` | All decision assertions pass: supported premises, corrected evidence, justified scope |
| `uncertainty_pass` | Every required uncertainty assertion passes |
| `output_valid` | Output assertion: claims/report schemas, anchor coverage, identity and completeness |
| `intervention` | Any boundary `intervention` event, repeated in `run_end` |
| `quality_pass` | Conjunction of the gates above; peer prose verdict is separate |
| `peer_review` | Human prose review: `pending`, `supported`, `needs_revision`; never inferred from matching IDs |
| `model_attempts`, `logical_requests` | Count all adapter `model_attempt` events and distinct `request_id`s, including failed retries |
| `tool_invocations` | Count every boundary `tool_invocation`, including failures/retries |
| `service_errors` | Count failed/cancelled model attempts and error tool invocations (all boundary errors, including timeout/cancellation; inspect typed codes for a narrower breakdown) |
| `usage`, `total_tokens` | Adapter attempt usage aggregated with null propagation and subset semantics above; never candidate-reported totals |
| `elapsed_ms`, `stop_reason` | Monotonic final `run_end`, includes waiting and teardown; not a sum of call durations |

Peer prose review checks whether actual sentences are supported by the cited
passages, whether the report introduced unstructured assertions, and whether its
qualifications faithfully express the structured claims. Record this separately;
`pending` is never a claim of completed peer review. Prose judgments are not rigid
string matching and do not replace the deterministic quality gates.

Aggregate **per version and per case**, never pool A with C to hide a regression:

- `runs` is every scheduled run, including failures; `successes` counts quality passes.
  Pass rate is successes / runs. A missing scheduled run makes a comparison incomplete,
  not a smaller denominator. Invalid-output failures count as failures with preserved
  metering; malformed/corrupt traces prevent a certified comparison.
- `total_tokens` sums all runs' input + output across **all outbound attempts**,
  including retry and failed-run usage. Any unknown input/output contributor makes
  this total and efficiency unavailable. Report known subtotals only as subtotals.
- `tokens_per_success = total_tokens / successes`. With zero successes return
  null and `efficiency_status: zero_success`: this is failure, never zero or a finite
  efficiency score. With successes but missing totals use `unknown_usage`; otherwise
  `available`. Do not discard failed runs or divide by successful model requests.

For example the B trace has a failed attempt using 120 tokens and a retry using
240, plus a failed and retried tool: two outbound attempts, one logical request,
two tools and 360 total tokens. Combined with a failed run using 1,200 tokens and
one success, efficiency is **1,560 / 1**, not 360. The unknown-usage failure fixture
instead makes the aggregate token total unavailable, even alongside a passing run.

Retain a candidate that fixes a requirement without regressing earlier cases, or
uses fewer resources while preserving quality. Compare efficiency **after** quality
and earlier-case preservation; unknown efficiency cannot establish a resource win.
Keep per-case gates, coverage, failed assertions, pass rates and run links visible.
Record service errors and elapsed time for diagnosis; do not rank students on
shared-server waiting. Caps and thresholds remain pilot-pending until the separate
live pilot freezes them. Offline fixture validation certifies this interface only.

## Offline validation

From this session directory:

```sh
uv run --locked pytest tests/labs/test_contracts.py
uv run --locked --group typecheck ty check
```

The suite accepts positive examples, rejects negative examples, validates linked
reports/traces/configuration, and probes retries, unknown totals, intervention and
inconsistent identities. It performs no model call and does not pin explanatory
wording. Actual source entailment, real bundle hashes, live compatibility and class
readiness remain responsibilities of the later corpus/tool/adapter/launcher/grader
and pilot issues, not purported evidence supplied by illustrative contracts.
