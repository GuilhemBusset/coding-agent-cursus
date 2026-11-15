# Later pilot: capture, sanitize, seal

There are no captured-live recordings in this issue. The supplied runs are
synthetic. Replay can demonstrate accounting/recovery and support offline editing;
it cannot establish model compatibility, autonomous research, costs or classroom
readiness. The later pilot owner records those observations separately.

1. Complete the session's locked setup. Save the actual student harness/prompts
   with `exercises.fixed.snapshot`; retain the snapshot, announced case/seed/trial,
   model/endpoint alias, settings and policy. Use an authorized API account and
   environment-only credentials. Never put keys or endpoint secrets in a command,
   config, prompt, report or fixture.
2. Run the fixed launcher with `--live` (a fresh independent run, not a scripted
   transport). Keep failures, partial output, retries, missing usage and the exact
   terminal reason. Retain request/attempt/retry identities, runtime status and
   effective settings alongside `config.json`, `policy.json`, `trace.jsonl`, typed
   output and report. The launcher's `captured_live` label records the selected
   execution mode, not a promise that the attempt succeeded.
3. Review a **copy** of the complete run before publication: all JSON/JSONL, raw
   outputs, markdown, provider text, prompts and saved versions. Look for the actual
   keys, authorization headers, routing URLs/query credentials, account/project
   identifiers and personal information. The fixed redactor is a first pass, not
   a substitute for reviewing captured artifacts. Replace sensitive text with an
   explicit redaction marker. Do not alter facts, usage, failure counts, retry
   linkage, settings, budgets or stop reasons. If a necessary redaction changes
   evaluated report/claims, regrade the sanitized copy and disclose that change.
4. Keep the original private; document capture date, operator, revision, selected
   environment and redactions in a companion note. If there was no outbound live
   attempt, do not publish it as a live recording. Never change a synthetic config
   to `captured_live`. Missing provider usage stays null, and prices/costs need
   separately dated source evidence.
5. Validate/regrade the sanitized copy with the same verified rating support used
   for capture, then seal its public artifact bytes. For the announced A variant,
   from the session directory (replace the saved run name and use its actual case):

   ```text
   mise exec -- uv run --locked python -m exercises.fixed.run grade --run exercises/runs/pilot-sanitized-01 --case a-find/variants/public-seed-20261115
   mise exec -- uv run --locked python -m exercises.fixed.replay --seal --run exercises/runs/pilot-sanitized-01 --case a-find/variants/public-seed-20261115
   mise exec -- uv run --locked python -m exercises.fixed.replay --run exercises/runs/pilot-sanitized-01 --out exercises/runs/pilot-replay-01
   ```

   Review `provenance.json`, retained source bytes, replay scorecard and all error
   links. Sealing must follow sanitization: changing an artifact afterwards breaks
   its digest. A seal establishes integrity since that point, not live provenance
   by itself. Published capture notes and retained private originals supply that
   provenance. Any replay still says `replay`, with source kind `captured_live`.

For the later pilot, the owner supplies the missing authorized live attempts and
capture review, dates/cost evidence and audience/rehearsal observations. Rerun the
fresh-live commands in the [rejoin runbook](../../../cursus/demos/replay/README.md),
then the grade/seal/replay sequence above. This issue prepares that workflow;
its offline tests make no claim that those observations have happened.
