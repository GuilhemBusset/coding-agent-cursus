# Saved versions and fresh runs

Run commands below from `sessions/02-research-agents/`, after the session setup
(`uv sync --locked` and `npm ci`; see the session README). Python orchestrates the
portable files/processes; Node runs the Pi TypeScript boundary. No global package,
account login, symlink or dependency from another session is used.

```sh
# Deterministic offline smoke: prepares support, snapshots, launches and grades,
# prints config/trace/accounting, then removes its temporary files. No API key.
uv run --locked python -m exercises.fixed.runtime.smoke

# Prepare the public rating revision from the shipped offline export:
uv run --locked python -m exercises.fixed.run prepare --export exercises/fixed/runtime/fixtures/rating-support.zip
# Alternatively omit --export to download the same pinned public revision.
# --export also accepts a directory exported by a previous preparation.

# Save current student work; names/destinations cannot be reused:
uv run --locked python -m exercises.fixed.snapshot --name baseline-v1
# Edit harness/ and prompts/, then save a separate candidate:
uv run --locked python -m exercises.fixed.snapshot --name candidate-v1

# Synthetic transport smoke with YOUR saved harness (not a completed agent):
uv run --locked python -m exercises.fixed.run run --snapshot exercises/runs/versions/candidate-v1 --case a-find --script exercises/fixed/runtime/fixtures/smoke-transport.json
# Paid calls require an explicit --live in place of --script and environment credentials.
# Regrade saved artifacts with the same verified public support:
uv run --locked python -m exercises.fixed.run grade --run exercises/runs/<run-id> --case a-find
```

All paths are regular Python/Node paths, including spaces and Windows drives.
`--cache` chooses a prepared cache; its default is `runs/cache/rating-v1`.
`--case` is a directory under the bundle's cases, for example
`a-find/variants/public-seed-20261115`. `--tools read,search` can select a subset of
that case's registered tools; `check_table` is available when registered by the
case. `--name` sets a unique run ID; otherwise one is generated. `--trial` and
`--seed` record the experimental identity; the seed does not promise deterministic
provider sampling. These launches are class-mode attempts; comparison/schedule
orchestration is separate work.

Snapshots copy every regular file in `harness/` and `prompts/`, reject symlinks,
and save sorted relative-path SHA-256 maps in `snapshot.json`. Immutability means
commands never overwrite saved versions and every launch checks their bytes;
it is not a filesystem permission or OS isolation guarantee. Editing the working
files cannot edit their copies. Each attempt copies the verified support and saved
version to a new temporary directory and starts a new Node process: no prior
messages, ledger, working files, module state or mutable settings are reused.
The session's locked npm install resolves dependencies; it is shared code, not
conversation state. Temporary roots honor `TMPDIR`/`TMP`/`TEMP` and are removed.

## Harness boundary

Supply `harness/main.ts`, exporting `async function run(api)`. Prompt files are
UTF-8. The API is intentionally small:

- `api.task` contains `question` and `context` only.
- `await api.model()` appends an assistant response to this run's conversation and
  returns a copy. It owns request dispatch, retries, usage and reservations.
- `await api.tools()` dispatches the latest successful response's registered tool
  calls in order, appends each tool result to the conversation, and returns copies.
  Repeating it does not dispatch the same call twice. Each invocation has its own
  admission check, including multiple calls in one response.
- `api.addMessage(text)` appends harness-selected research memory/instructions as
  a user message. `api.saveOutput(output)` saves a partial candidate result.
- `api.cancel()` aborts active model/tool work and prevents further dispatch.
  `api.intervention('edit' | 'steer' | 'resume')` records human intervention; every
  run starts without intervention. There is no interactive resume workflow here.

Await each operation. Concurrent dispatch is refused so reservations cannot race.
The harness chooses progress, recovery and completion. Return
`{claims, claim_anchors, markdown, stop_reason}`; the last field is `completed` or
`no_progress` (default `completed` for a returned result). The first fields are the
arrays from the public claims/report schemas and Markdown with the corresponding
anchors. The boundary supplies run/case/variant identity and fixed output paths.
Candidate counters, pass flags and claimed usage are saved as candidate output
but are never used for measurement or grading. After catching a boundary stop,
the harness can still return a result or call `api.saveOutput(output)` to retain
its work for grading. Saving output preserves the exact stop reason and does not
permit further dispatch. Without a boundary stop, no returned result means
`no_progress`; if no result was saved, grading uses an explicitly unfinished report.

## Exactly what reaches the model

Automatically assembled context consists of:

1. A system message containing a filename-to-text map of all saved prompt files
   (except `.gitkeep`), plus the **claims, report and common v1 JSON schemas** as
   the output contract. Prompt files must contain only intended research inputs.
2. A user message containing exactly the selected public case's `question` and
   `context` fields. `reference_path`, examples and the rest of `case.json` are
   not inserted.
3. JSON-Schema definitions/descriptions for only the selected tools.
4. This attempt's assistant messages, harness `addMessage` text and tool-result
   messages. The model receives `result` from the Python bridge: run/tool identity,
   status, bounded evidence text/search hits/table computations, citations,
   truncation and typed errors. Bridge invocation/audit details are saved separately,
   not inserted as additional context. `read`/`search` resolve only corpus IDs;
   `check_table` accepts registered row parameters, never code or a filesystem path.

The adapter serializes these into text-only OpenAI Responses input, adds the
configured model, output maximum, reasoning `none`, `store:false` and streaming.
`requests.jsonl` captures that actual outbound body after redaction. The independent
boundary tests capture continuation with real corpus results and verify automatic
reference/rubric exclusion. Public references, graders and scorecards remain
inspectable to students, including in the public cached bundle; they are never
loaded as automatic research messages or tools. A harness can deliberately read
public files or put a reference in its own prompt. This is inspectable experiment
control, **not an adversarial sandbox or OS isolation**.

No environment field is automatically converted to a model message. Python passes
only operational `PATH`/`Path`, Windows `SYSTEMROOT`/`SystemRoot`/`WINDIR`/`COMSPEC`/
`PATHEXT`, `TMPDIR`/`TMP`/`TEMP`, `LANG`/`LC_ALL`, `SSL_CERT_FILE`/`SSL_CERT_DIR`, and
sets `PYTHONIOENCODING=utf-8`. `OPENAI_API_KEY`, `COURSE_API_KEY` and
`COURSE_ENDPOINT_<ALIAS>` additionally cross into the worker **only to initialize
the adapter and fixed redactors**, then are removed before importing the harness or spawning Python
tools. There is no inherited `NODE_OPTIONS`, `PYTHONPATH`, Pi account/cache setting
or arbitrary environment passthrough. The endpoint URL and key stay in the fixed
adapter/redactor closures; saved configuration contains an endpoint alias. Error codes are fixed;
artifacts redact credentials, Bearer headers and URLs (including query/userinfo).
Raw worker/provider stderr is never saved. Do not put credentials in source/prompts.

## Rating support and accounting

`fixed/config/rating-bundle.v1.json` names public revision
`75e9de64f9b8f38ce88deec76cd92fca5f7bfb50` and hashes
`rating-files.v1.json`, whose explicit paths/digests cover cases, references, corpus
files, evaluator, schemas, bridge, tools, adapter and adapter configuration.
The shipped ZIP exports exactly those public bytes. Preparation checks every
member before creating a cache; launch and regrading recheck it. Execution/imports
use only manifest members, so unrelated cache files do not become support.
Missing or mismatched content fails explicitly, with no working-tree fallback.
Keep the cache for peer-review evidence links. To repair corruption, prepare a new
cache path from the export rather than editing it. The local boundary policy and
runtime settings remain explicit experiment controls, saved and hashed per run.

`--mode development` deliberately uses local cases/support; `run-inputs.json` says
`development`, and `config.json` records `development-working-tree`/illustrative.
It cannot be regraded as a pinned rating run. `evidence_kind` is separately
`synthetic` for `--script` or `captured_live` for an authorized `--live` dispatch;
synthetic tests are not live compatibility or autonomy evidence.

`--settings <json>` accepts the shape in `fixed/config/run.v1.json`. It configures
provisional 12-request, 20-tool, 30,000-token caps, request/tool/run deadlines,
provider/model/endpoint alias, bounded output (16–8192) and retries (0–2).
Request timeouts are 1–120,000 ms. The adapter's internal retries and SDK retries
are disabled; the boundary admits each retry independently. A known-usage service
failure before content may retry. Unknown input or output usage prevents retries
and any further work. Cached input counts once within input tokens; reasoning
counts once within output tokens. Missing usage remains null, never zero or a
reservation treated as observation.

For the selected GPT snapshot and text-only Responses protocol, admission bounds
input by the entire UTF-8 serialized envelope plus 4,096 framing tokens, 128 per
input record and 512 per tool declaration; it also reserves the enforced output
maximum. These deliberately conservative bounds include prompts, schemas, tool
results and protocol framing. The complete outbound envelope is inspected at
fetch, before the transport is called. Other model IDs or unsupported envelope
forms stop as `reservation_unknown`; adding another model needs a fixed safe
reservation profile. Compatible provider/endpoint routing remains configurable.
Known usage reconciles the reservation before the next request. This may refuse a
request that would fit in practice; provisional caps need live pilot calibration.

Artifacts under `runs/<run-id>/` retain successful and failed attempts:

- `config.json`, `policy.json`, `run-inputs.json`: identities, hashes, selected
  tools, settings, limits, public revision and development/rating label.
- `trace.jsonl`: independent model attempts, each dispatched tool, intervention and
  terminal event, with retry linkage, observed usage and elapsed milliseconds.
  Tool inputs use the bridge's normalized successful arguments. Error-only read/
  search envelopes materialize bounded defaults for the closed v1 schema; the
  journals retain the actual original arguments, including omitted defaults.
- `dispatches.jsonl`: start journal; a killed worker's in-flight attempts are
  reconstructed with unknown usage, never silently lost.
- `reservations.jsonl`: admitted/blocked bounds and prior observed usage, **separate**
  from trace observations and `accounting.json` totals.
- `requests.jsonl`, `responses.jsonl`, `messages.json`, `tool-results.jsonl`,
  `effective-settings.jsonl`: sanitized requests, partial responses and tool audit.
- `candidate-output.json`, `claims.json`, `report.json`, `report.md`: raw sanitized
  candidate fields and fixed identity envelopes; the unfinished fallback is
  intentionally not a successful answer.
- `runtime-status.json`: detailed terminal cause (`accounting_unknown`, `timeout`,
  `cancelled`, `run_timeout`, `reservation_unknown`, `reservation_exceeded`,
  `harness_error`, or a cap/output/progress reason). The closed v1 trace maps extra
  causes to `service_error`; request events preserve timeout/cancellation causes.
  Cancellation can be the primary cause with `accounting_status:unknown` and null
  aggregate tokens. `known_observed_tokens` is only the known subtotal.
- `accounting.json`, `scorecard.json`, `grading.json`, `peer-review.md`: aggregates
  from trace, pinned post-run grading and a separate pending peer prose audit.

A stopped run is still a recorded attempt. The CLI returns a JSON status even when
quality fails; startup/input/bundle failures exit 2. Check `runtime-status.json`
and `scorecard.json` independently. Reusing an output directory fails. No comparison,
replay certification or completed teaching harness is supplied by this boundary.

## Validation and limits of this evidence

```sh
uv run --locked pytest tests/labs/test_run_boundary.py tests/labs/test_run_accounting.py
npm run typecheck
uv run --locked python -m exercises.fixed.runtime.smoke
```

Tests prepare the pinned export offline, use real Pi serialization and real Python
corpus tools, and remove their temporary caches/workspaces after printing diagnostics.
`fixed/runtime/examples/` contains representative **synthetic** config/trace from
the smoke. Regenerate with `...runtime.smoke --capture exercises/fixed/runtime/examples`.
This validates boundary mechanics; it makes no paid API, live autonomy, native OS
execution or classroom readiness claim. After normal session setup, the owner can
rerun these three commands on macOS, Windows and native Linux for actual platform
execution evidence. Live compatibility/pilot/rehearsal remain their scheduled
Session 2 deliverables, not passes inferred from scripted transport.

Named owner evidence obligations (implementation and offline checks are supplied):

- **OO185-macos / platform:macos**, **OO185-windows / platform:windows**, and
  **OO185-native-linux / platform:native-linux**: execute the three validation
  commands above after the documented session setup on each native OS; retain
  terminal output, OS/tool versions and the printed synthetic config/trace.
  Linux-hosted type checks for those targets do not satisfy native execution.
- **OO185-live / credentials:OPENAI_API_KEY**: during the scheduled authorized
  Session 2 pilot, save a harness version, set the API key and endpoint environment,
  run `uv run --locked python -m exercises.fixed.run run --snapshot
  exercises/runs/versions/baseline-v1 --case a-find --live`, and retain sanitized
  request/tool-continuation, usage, cancellation and status artifacts. Verify the
  actual provider/model/endpoint compatibility; these offline fixtures supply no
  live autonomy or classroom calibration evidence.
