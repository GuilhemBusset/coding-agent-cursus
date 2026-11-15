# Completed experiment records

Recorded 15 November 2026 by the builder from offline executions of the public
commands in [README.md](README.md). These are **synthetic** findings: prescribed
provider answers and usage passed through real Pi, tools, accounting and grading.
There is no captured-live evidence and no replay of a live capture. All generated
scorecards still mark peer prose review pending. The records below establish the
machine workflow and the stated trace lesson, not live model efficacy or rehearsal.

## Saved versions and hashes

Every version includes checkpoint-04 code; only the rejected harness candidate
changes its stopping threshold. Full SHA-256 values (not abbreviated labels):

| Snapshot ID / directory in `versions/` | Snapshot SHA-256 | Harness group SHA-256 | Prompt group SHA-256 |
| --- | --- | --- | --- |
| [harness-baseline](versions/harness-baseline/snapshot.json) | `fe9198fe88832a1186396770fb68c1c26cdd31fb0a0b8f15341fbe9a93e6ce04` | `b42e02bcc6aa4fdb25b58cbb5ea908499f278ca6c35484c1a6b1173967cb1287` | `421a85c7a41a51eb9753b0d2b31d487bc325e20986d16a8086b32931e83d21ad` |
| [harness-candidate](versions/harness-candidate/snapshot.json) | `7b991f2f323752fdc73bbba9cd3d92807c75587bcc047a1a208e1b21e5f21efb` | `a8689dca3190e89b4bf77629174d456210d8c3aa69c4df511f9c7021a763cf7e` | `421a85c7a41a51eb9753b0d2b31d487bc325e20986d16a8086b32931e83d21ad` |
| [prompt-structured](versions/prompt-structured/snapshot.json) | `55b0d18219d6c3dabb1020462a5312bd2a58a96c9b174213392354bdc106b709` | `b42e02bcc6aa4fdb25b58cbb5ea908499f278ca6c35484c1a6b1173967cb1287` | `a5915b0e38ef27f24f255a2ce1ad9e98ea15eec390a4f3f3a2823f5133d0a061` |
| [prompt-structured-paraphrase](versions/prompt-structured-paraphrase/snapshot.json) | `0d147a4041996e773cf8ab09520b044ef42f97d5a93f60a3a0175bafd40921dd` | `b42e02bcc6aa4fdb25b58cbb5ea908499f278ca6c35484c1a6b1173967cb1287` | `028a788a432057e853f1179db1c3b6f6e6000e0a7e88e3d30e2363915165aaee` |
| [prompt-vague](versions/prompt-vague/snapshot.json) | `d7959a62a9a5c747c0b1827d16e8bccd55c175a2ca770ed13d4d9acb9cfa4530` | `b42e02bcc6aa4fdb25b58cbb5ea908499f278ca6c35484c1a6b1173967cb1287` | `f81006acf4edd59662db30f1a513d8fd13d3c7b165127b3be3d8d4a148cbffba` |
| [prompt-vague-paraphrase](versions/prompt-vague-paraphrase/snapshot.json) | `7190c5c6d4d6e5f333e2d5cd0e020c20c1bef5c96dc34ba13fb8fbc2bdf3c4f8` | `b42e02bcc6aa4fdb25b58cbb5ea908499f278ca6c35484c1a6b1173967cb1287` | `e127ed1f5c0776d12149555c29afb43bd34c13b5417c572148eadc86c7978de2` |

Shared controls in all three experiments: `class`; one trial each of
A/public-seed-20261115 (seed 20261115), B/public-seed-20261125 (20261125),
C/public-seed-20261135 (20261135); OpenAI, endpoint alias `openai`,
`gpt-5.4-mini-2026-03-17`; temperature and sampling seed null, reasoning none,
max output 1024; budgets 12 model / 20 tool / 30,000 input+output tokens per run.
Timeouts and retries are the unchanged [public settings](../config/run.v1.json).
A/B expose read/search; C also exposes check_table. No human interventions.

| Shared hash | SHA-256 |
| --- | --- |
| model | `249ad911fe12bcd2c59cd8d26b798ed19d63ad5fd21875f8914ea2356b52a2ae` |
| evaluator | `5119f8227e136f297974139156d0098a4ea4cfe3aa524d235efa99a714bf07d7` |
| rating_bundle | `0be1a010c38b277173a17abe558b4d6a4c9c9f7aa447b07ba0a95cbaa1ecc856` |
| A settings | `9413b3729a2837025a2083cdccb4688c32d31fa59f123e3a58812206e4ccf013` |
| A corpus | `3d358f811cd9ddfa86409ebaa6fdc7bb601c7d255430924417ee8ff888bfa799` |
| B settings | `9413b3729a2837025a2083cdccb4688c32d31fa59f123e3a58812206e4ccf013` |
| B corpus | `b2263028f83a27b3070b2d26cf88145b82af468c58439243077f29bd4fc5bb65` |
| C settings | `98ff9cfbe4a80935c06bbff6a9834e2932747611b1dfeb7297f589b0e4b21513` |
| C corpus | `01e0d65b2fec670885a2f75d68dc8587c4f023ee3be007ec01639aada12e067e` |

Each comparison retains these in `shared.json` and per-attempt `config.json`.
The class schedule, support files and settings are shared across both roles;
workspace/run IDs differ, as they must for independent attempts. All attempts,
including early stops, remain in resource totals and scheduled denominators.

## Harness · propose → probe → revert → compose

- Roles: B driver, A navigator (teaching allocation, not a classroom observation).
- Hypothesis/prediction: stopping after one retrieval adds no retained evidence
  will save tokens without reducing successful answers. Sole edit:
  `harness/policy.ts`, `stagnant >= 2` → `stagnant >= 1`.
- Frozen: prompt bytes, all shared controls above, public cases and scripts.
- Versions: `harness-baseline` → `harness-candidate`, hashes above.
- Command: `uv run --locked python -m exercises.fixed.evaluate compare --experiment exercises/fixed/examples/harness.json --output exercises/runs/harness-example`.
- Observed exit 1; comparison evidence kind synthetic. Complete artifacts:
  [shared controls](../../runs/harness-example/shared.json),
  [before](../../runs/harness-example/before.md), [after](../../runs/harness-example/after.md),
  [comparison](../../runs/harness-example/comparison.json) (generated by the command).

| Measurement, all scheduled attempts | Baseline | Candidate |
| --- | --- | --- |
| A / B / C successful attempts | 1/1 / 1/1 / 1/1 | 0/1 / 0/1 / 0/1 |
| Decisive requirement checks | 34/34 | 0/34 |
| Required facts / coverage | 35/35 · 100% | 0/35 · 0% |
| Citation checks | 35/35 | 3/3 (uncertainty-only partial reports) |
| Required uncertainty checks | 3/3 | 0/3 |
| Output checks | 3/3 | 0/3 |
| Input / output tokens | 1200 / 240 | 600 / 120 |
| Cache-read / cache-write / reasoning tokens | 120 / 0 / 24 | 60 / 0 / 12 |
| Total input+output tokens | 1440 | 720 |
| Model attempts / logical requests / tool calls | 12 / 12 / 21 | 6 / 6 / 6 |
| Retries / service errors / interventions | 0 / 0 / 0 | 0 / 0 / 0 |
| Stop reasons | completed × 3 | no_progress × 3 |
| Tokens per success | 480 | undefined (zero successes) |

Earlier-case regressions: **both A and B** drop from pass to fail, as does C.
Candidate failures include `decisive.A-method-set`, `decisive.B-recommendation`,
`decisive.C-rows` and `uncertainty.C-uncertain-demand`; the full list is in
`comparison.json` and each scorecard. Three passing citation checks on partial
unknown claims do not supply the missing answers. Prose support audit: pending;
open each `peer-review.md` and check the actual passages/rows, not claim IDs.

Trace witness: in `runs/baseline-01/trace.jsonl`, `request-1`/`tool-1` reads
the scope; `request-2`/`tool-2` searches; requests 3 and 4 read support and
produce a completed answer. The candidate makes the same first two requests
then ends `no_progress`, preserving its partial evidence. Compare
[baseline trace](../../runs/harness-example/runs/baseline-01/trace.jsonl) and
[candidate trace](../../runs/harness-example/runs/candidate-01/trace.jsonl),
their `requests.jsonl`, `tool-results.jsonl`, `report.md` and `scorecard.json`.
C baseline also executes a successful check_table; candidate never reaches it.

**Decision: revert.** The 720-token reduction cannot offset loss of every
quality gate. Retained lesson: search is discovery and can legitimately add no
retained evidence; one such step does not establish a stall. This is a causal
observation about this stopping policy on these public scripted sequences,
not a measured live-model tradeoff. Elapsed time is diagnostic only and varies
per host; inspect `elapsed_ms` in generated before/after scorecards, never rank it.

## Prompt · original pair and announced paraphrase rerun

- Roles: A drives the original pair; B drives the paraphrase rerun; the other
  partner audits. These are assigned roles, not evidence of a rehearsal.
- Original hypothesis: explicitly naming question, scope, evidence, uncertainty
  and output will improve requirement and citation performance over a vague
  request. Sole changed variable: `prompts/system.md`.
- Paraphrase hypothesis: that effect will survive the already-announced
  rewordings. Sole variable within that comparison: vague vs structured
  paraphrase. Do not choose wording after looking at scores.
- Versions: `prompt-vague` → `prompt-structured`; then
  `prompt-vague-paraphrase` → `prompt-structured-paraphrase`. Hashes above.
- Frozen: byte-identical checkpoint-04 code across **all four versions**,
  plus the same controls, cases, scripts, seeds and one-trial schedule above.
- Commands (from session):

```sh
uv run --locked python -m exercises.fixed.evaluate compare --experiment exercises/fixed/examples/prompt.json --output exercises/runs/prompt-example
uv run --locked python -m exercises.fixed.evaluate compare --experiment exercises/fixed/examples/paraphrases.json --output exercises/runs/paraphrases-example
```

Both returned exit 1, synthetic, machine recommendation revert. Each row below
applies independently to **both** pairs; totals are per version, not combined
across the four versions.

| Measurement | Vague / vague paraphrase | Structured / structured paraphrase |
| --- | --- | --- |
| A / B / C successes | 1/1 / 1/1 / 1/1 | 1/1 / 1/1 / 1/1 |
| Decisive checks / required facts | 34/34 / 35/35 | 34/34 / 35/35 |
| Coverage / citation checks / uncertainty checks | 100% / 35/35 / 3/3 | 100% / 35/35 / 3/3 |
| Input / output / total tokens | 1200 / 240 / 1440 | 1200 / 240 / 1440 |
| Cache-read / cache-write / reasoning tokens | 120 / 0 / 24 | 120 / 0 / 24 |
| Model attempts / logical requests / tool calls | 12 / 12 / 21 | 12 / 12 / 21 |
| Retries / service errors / interventions | 0 / 0 / 0 | 0 / 0 / 0 |
| Stops / tokens per success | completed × 3 / 480 | completed × 3 / 480 |

Earlier-case regressions: none in either pair; A/B/C all preserve passing
quality. No failed requirement assertion. Citation results are machine checks;
peer prose review remains pending. Elapsed totals vary per rerun and are not
part of this decision; the generated scorecards retain them.

Evidence links: [original comparison](../../runs/prompt-example/comparison.json),
[paraphrase comparison](../../runs/paraphrases-example/comparison.json), their
`shared.json`, before/after scorecards and `runs/{baseline,candidate}-01/requests.jsonl`.
In each pair, compare `request-1` provider instructions: prompt bytes differ;
all four requests still receive the prescribed four script steps. Inspect
the corresponding `trace.jsonl`, `report.md`, `scorecard.json` and `peer-review.md`.

**Decision for each pair: keep the simple vague baseline / revert candidate.**
No measured requirement improvement or efficiency gain supports adoption here.
Retained lesson: scripted equality validates controlled execution and grading,
but cannot test live sensitivity to wording. It supports neither the predicted
efficacy claim nor its opposite. For a live claim, run actual provider calls
under the same controls and record those separate captured-live findings.
