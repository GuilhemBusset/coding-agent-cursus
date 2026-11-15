# Experiment record

Copy this record once per comparison (including the paraphrase rerun). A passing
simple baseline is acceptable; “keep baseline” needs no extra machinery. Fill the
hypothesis before editing, then link actual saved artifacts. Completed records:
[public examples](fixed/examples/completed-records.md).

| Field | Your record |
| --- | --- |
| Block / driver / navigator / date | Harness 70–85 or prompt 85–105; roles |
| Hypothesis and prediction | Which requirement improves, or which work decreases? |
| Sole changed variable | Exact harness policy **or** prompt form; paraphrase pair if used |
| Frozen variables | Prompt or code; provider/model/endpoint, sampling, budgets, cases, seeds, trials, tools, rating bundle |
| Evidence kind | Synthetic scripted execution / replay of named capture / captured live; mixed findings labelled separately |
| Saved versions | Baseline and candidate paths, snapshot IDs and SHA-256 values |
| Control hashes | From each run's config: harness, prompt, model, settings, corpus, evaluator, rating_bundle; shared.json path |
| Public configuration / command | Experiment JSON, announced A–C variants/seeds/trials; exact run command and exit status |
| Requirements | Per-case quality passes; decisive failures and assertion IDs before → after |
| Coverage | required_facts_met / required_facts_total and percentage before → after |
| Citations / prose audit | Citation checks before → after; inspect actual spans/rows and claim prose, record reviewer or pending |
| Resources, **all attempts** | Input/output/cache-read/cache-write/reasoning tokens (unknown stays unknown); total tokens; model attempts/logical requests/tool calls; retries/errors/interventions; elapsed time diagnostic only |
| Efficiency | Total tokens / successful attempts; undefined if no successes or insufficient usage |
| Earlier-case regressions | A and B before → after (plus C); failed attempts stay in denominator |
| Trace evidence | Baseline/candidate trace paths and event/request/tool IDs; reports and scorecards |
| Keep / revert and explanation | Quality and earlier-case preservation first, efficiency second; baseline may already suffice |
| One retained lesson and limit | What the trace supports; what this evidence cannot establish |

Scripted provider usage and responses are synthetic even when the real Pi program,
tools, accounting and grader execute them today. Rerunning a script does not turn
it into a captured-live replay. A replay names its original capture and proves
re-execution of recorded events, not a new live model response. Only an actual
provider call is captured live. Never present a synthetic/replayed prompt difference
as evidence of live efficacy. Keep peer prose review separate from machine gates.
