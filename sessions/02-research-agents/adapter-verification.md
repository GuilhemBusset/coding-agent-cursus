# Session 2 model connection

Status on **2026-11-14**: offline adapter verified; **live OpenAI compatibility UNVERIFIED**.
No `OPENAI_API_KEY` was available to this implementing operator. A subscription to a
coding agent is not API evidence. Guilhem Busset owns the live rerun below.

## Fixed comparison and supported boundary

The comparison selects `gpt-5.4-mini-2026-03-17`, `POST /v1/responses`, streaming
function calls, `@earendil-works/pi-ai` **1.5.2** and `@earendil-works/pi-agent-core`
**1.5.2**. The session's existing package lock also resolves OpenAI SDK 7.19.0.
No dependencies were added or upgraded. Sources consulted 2026-11-14:

- [Official model documentation](https://developers.openai.com/api/docs/models/gpt-5.4-mini):
  dated snapshot, Responses, function calling, streaming and reasoning effort `none`.
- [Responses create reference](https://developers.openai.com/api/reference/resources/responses/methods/create):
  output bound, streamed response events and usage details.
- [Reasoning guide](https://developers.openai.com/api/docs/guides/reasoning):
  output includes reasoning tokens; the output bound covers both visible and reasoning output.
- [Pi AI documentation](https://github.com/earendil-works/pi/blob/main/packages/ai/README.md)
  and [Agent documentation](https://github.com/earendil-works/pi/blob/main/packages/agent/README.md).
  For the actual pinned behaviour, inspect the installed 1.5.2
  `pi-ai/dist/api/openai-responses.js` and `openai-responses-shared.js`, and
  `pi-agent-core/dist/types.d.ts`; upstream main can change. The package versions
  and exact dependencies are recorded in the session manifest and lock.

Documentation supports the selection; it does **not** certify account access or
live compatibility. The opt-in smoke must establish those independently.

`exercises/fixed/config/model.ts` supplies the configuration and strict validator.
One adapter instance fixes provider, endpoint alias, model, settings, deadline and
retry count for a comparison. The OpenAI provider requires the selected snapshot.
`openai-compatible` permits a different model identifier for a Responses-compatible
endpoint. Other protocols and unknown fields fail before dispatch. There is no
sibling-service integration or global Pi configuration/credential store.

| Setting | Effective request |
| --- | --- |
| `reasoning: "none"` | Pi's reasoning model with no effort override sends `reasoning: {effort: "none"}` |
| `max_output_tokens: 1024` | Pi `maxTokens` becomes `max_output_tokens`; accepted range 16–8192 prevents Pi's minimum clamp |
| `temperature: null`, `sampling_seed: null` | Both omitted; no assumption of temperature or seed support, non-null values rejected |
| streaming / storage / cache policy | `stream: true`, `store: false`, cache retention `none`; no global cache preference or session identifier |
| timeout / retries | 30 seconds per attempt, one visible retry by default; configurable 1–120000 ms and 0–2 retries |

The output ceiling is an instructional bound below the model's documented maximum.
No additional sampling parameters or reasoning policies are exposed. Supporting
them later requires documentation, mapping tests and a renewed live smoke.

To use the supplied connection with Pi:

```ts
import { Agent } from "@earendil-works/pi-agent-core";
import { createAdapter } from "./fixed/model/adapter.ts";
const connection = createAdapter();
const agent = new Agent({ streamFn: connection.streamFn,
  initialState: { model: connection.model, systemPrompt: "Your fixed prompt", tools: [] } });
await agent.prompt("Your question");
// Save connection.config, connection.events and connection.effectiveSettings.
```

Use one adapter per run. `events` contains contract v1 `model_attempt` records.
`effectiveSettings` is a sanitized companion record keyed by **run_id + attempt_id**,
including the reasoning policy and observed HTTP status; no trace-schema change
is required. Add these attempt records to the later launcher's complete trace;
the launcher owns tool events, run_end, global sequence allocation and run budgets.
Pi message usage remains its SDK convenience representation; **use adapter attempt
usage for accounting**, because Pi fills missing fields with zero.

Every dispatch crosses the injected fetch meter. Pi's provider retries are set to
zero and its OpenAI SDK explicitly uses zero retries. Redirects are manual, so no
unmetered follow-up request occurs. Only network failures, 429 and 5xx before
partial output can retry; retries retain logical request identity and link attempts.
They do not change settings. Each attempt has its own deadline covering dispatch
and streaming. Caller cancellation stops admission or cancels an in-flight attempt.
The maximum logical-call wall time is `(retries + 1) * timeout_ms` plus local work.
Timeout/cancellation/failure retains partial output and observed usage, with a typed
error; raw exceptions, provider error bodies, headers and routing URLs are not saved.
Known credentials, bearer headers and URLs are redacted from streamed output too.

Input tokens **include** cached input; output tokens **include** reasoning. Raw
Responses usage is observed before Pi normalizes it. Missing fields remain null;
absent usage is unknown. An explicit compatible-endpoint `cache_write_tokens`
subset is retained. Standard OpenAI usage has no separate cache-write category;
its absent write count is zero only when a usage record exists. Subset counts are never added
again. Aggregation must propagate null, as the existing contract validator does.

## Offline command evidence

From the repository root after the session setup:

```sh
uv run --no-project --python 3.12 python setup/session-02-research-agents.py --adapter-smoke --offline
```

Observed 2026-11-14 on this Linux host, Node 24.15.0, both Pi packages 1.5.2:
synthetic evidence; provider `openai-compatible`, alias `fake`, same snapshot,
256 output tokens, reasoning none, no sampling settings, no retries. The helper
started a loopback HTTP Responses endpoint, resolved its URL through
`COURSE_ENDPOINT_FAKE` and passed its credential through `COURSE_API_KEY`.
The same Agent/adapter entry point produced one streamed `echo` call, executed its
result and sent a continuation: **2 successful requests, 200 input tokens including
20 cached, 40 output including 4 reasoning**. A separate 30 ms stalled request was
counted and cancelled with `timeout`, all token fields null. Total cost remained
unknown; the known synthetic subtotal was $0.0003165. Nothing here incurred an API
charge or proves the selected model works live.

The registered `model-adapter.test.mjs` suite additionally proves exact retry,
partial failure, missing usage, cancellation and secret-redaction behaviour. Pytest
validates emitted attempts against existing schemas and verifies unknown totals.
Invalid provider configuration exits 2 with
`provider must use the OpenAI Responses protocol; requests sent: 0`:

```sh
uv run --no-project --python 3.12 python setup/session-02-research-agents.py --adapter-smoke --invalid
```

The nonzero exit is expected. The pytest suite checks it. Unsupported generation
settings also fail with a sanitized diagnosis before transport invocation.

## Live obligation — Guilhem Busset

From a fresh clone, follow [the setup runbook](../../setup/README.md#session-2-python-and-pi-toolchain)
to install mise/uv and the locked session packages. Set an authorized, separately
billed project API key in the environment as described there, then from the repo root:

```sh
uv run --no-project --python 3.12 python setup/session-02-research-agents.py --adapter-smoke --live
```

This explicit opt-in makes at most **three** outbound attempts: two 256-token
Agent turns (tool and result continuation), then one deliberately short 5 ms
deadline probe, with retries disabled. It prints sanitized JSON. Missing auth,
tool/continuation failure or missing timeout outcome exits nonzero. Auth success
is reported separately from tool success; authentication failures retain sanitized
HTTP status. No key is printed. A timed-out request may still be billed by the provider.

Publish the output here, with date, exact snapshot/route/package/runtime versions,
effective settings per attempt, accepted auth, actual tool call/result continuation,
sanitized trace, counted requests, known and unknown usage, timeout outcome and
dated cost calculation. All those **live** observations are currently missing.
If timeout usage is unknown, publish the known subtotal and reconcile total cost
against the project's API usage/billing dashboard; never label unknown cost zero.
Retain failures honestly and rerun after resolving permissions, billing or limits.
Real macOS/Windows execution remains to be observed by the owner on those systems;
the implementation uses portable Python/Node, with no exercise shell dependency.

## Prices, controls and migration

The [official model price table](https://developers.openai.com/api/docs/models/gpt-5.4-mini),
checked 2026-11-14, lists standard text rates per million tokens: **$0.75 input,
$0.075 cached input, $4.50 output**. For each attempt with known input I, cached C
and output O: `USD = ((I-C)*0.75 + C*0.075 + O*4.50)/1_000_000`.
Example (illustrative): I=1000, C=200, O=100 (including any reasoning) costs
$0.001065. Sum **all** attempts, failed requests and retries included. Unknown
usage makes the total unknown; tax, future price changes and other service fees
are outside this token estimate. Local echo/tools have no hosted-tool fee.

Use a dedicated API project, minimal key permissions, a small funded allowance,
spend alerts and a class stop authority. Limit concurrent pairs and stagger starts;
monitor actual project usage during class. The future launcher enforces the
provisional per-run 12 model attempts / 20 tools / 30000 total tokens, cancels at
admission boundaries and retains partial failures; **this adapter alone does not
enforce run-wide budgets**. Retry attempts consume those budgets. Reason about
worst-case context plus bounded output before admission, rather than relying on
reported usage only after a call. Pilot calibration of classroom caps is separate.
Provider request/token limits vary by account tier and model; 429s can be shared
across pairs, cancellation need not cancel server billing, and project budget
alerts are not a guaranteed synchronous spending cutoff.

For a later provider migration: verify a concrete model/route and API access;
select a new comparison config and endpoint alias; review supported reasoning,
sampling, output and context limits; check streamed tool arguments and result
continuation; audit SDK/provider retries, redirects and cancellation; recheck raw
usage availability and cache/reasoning subsets; rerun redaction tests; update dated
prices/cost logic; run offline endpoint tests and the authorized live smoke; then
repeat pilot calibration. A protocol other than compatible Responses needs a new
validated transport mapping. Do not integrate `research-harness-inference` as part
of this connection.
