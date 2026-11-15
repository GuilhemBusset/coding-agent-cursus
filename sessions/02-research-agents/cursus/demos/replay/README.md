# Outage/rejoin card — 45–65 minute recovery checkpoint

Before class, install the locked session dependencies while online. Open the
[public schedule and expected outcomes](../../../exercises/fixed/fixtures/README.md),
the completed [bounded-recovery example](../../../exercises/fixed/faults/recovery.ts),
and [source provenance](../../../exercises/fixed/fixtures/faults/transient-read/provenance.json).
The [presentation copies](../../fixtures/replay/) are static synthetic evidence;
execute support from `exercises/fixed/`.

Say: “The service is unavailable. We can inspect a failure and keep editing and
checking locally. This replay cannot certify live autonomous research.” Drivers
continue alternating. Keep the single-agent program and fixed research prompt;
this recovery block precedes prompt experiments.

From `sessions/02-research-agents/`, use a fresh output name:

```text
mise exec -- uv run --locked python -m exercises.fixed.replay --run exercises/fixed/fixtures/faults/transient-read --out exercises/runs/outage-read-01
mise exec -- uv run --locked python -m exercises.fixed.replay --run exercises/fixed/fixtures/faults/tool-budget --out exercises/runs/outage-budget-01
```

Open each output's `config.json`, `source-trace.jsonl`, `trace.jsonl`,
`accounting.json`, `scorecard.json`, `provenance.json` and `peer-review.md` in the
editor. Observe one failed read plus one successful identical retry; then 20
counted tools and a stop before the 21st dispatch. Check `retry_of`, unchanged
budgets, fresh replay envelope IDs and the synthetic source kind. Partial answers
fail quality; the scorecard does not award success merely for recovering.

Edit students' `exercises/harness/main.ts` to validate arguments, retain errors,
retry at most once and stop when retrieval adds no new evidence. The completed
example is a public aid to this edit. Run the deterministic checks offline:

```text
mise exec -- uv run --locked pytest tests/labs/test_fault_replay.py
mise exec -- npm run typecheck
```

To execute the supplied recovery example and fault afresh, still offline:

```text
mise exec -- uv run --locked python -m exercises.fixed.faults --scenario transient-read --out exercises/runs/edited-recovery-reference-01
```

That command runs the supplied example, not the student's edited harness. Review
and typecheck student edits; later checkpoint commands can execute their own
saved program with scripted transport. Do not count the reference run as a
student experiment or replay as live-model evidence.

When service returns, keep the outage artifacts. Rejoin from the student's saved
research program: ensure `harness/main.ts` exports `run(api)`, save current edits,
and start a fresh workspace with the same announced task and budgets. With the
configured provider credential in the environment and verified rating cache ready:

```text
mise exec -- uv run --locked python -m exercises.fixed.snapshot --name rejoin-01
mise exec -- uv run --locked python -m exercises.fixed.run run --snapshot exercises/runs/versions/rejoin-01 --case a-find/variants/public-seed-20261115 --seed 20261115 --trial 1 --live --name rejoin-live-01
```

This last command uses the API and may incur cost. If no rating cache was prepared,
run `exercises.fixed.run prepare` after connectivity returns first. Use fresh
version/run names on subsequent rejoin attempts. Confirm actual dispatch,
`captured_live` config, effective settings, errors/usage and terminal status;
then inspect the independently generated scorecard and peer-review checklist.
A service failure is retained evidence, not a live success. For a later published
pilot recording follow the [capture/sanitization procedure](../../../exercises/fixed/faults/CAPTURE.md).
