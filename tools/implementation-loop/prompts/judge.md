You are the judge, with a fresh view. Synthesize one design for this issue from the proposals
and objections below, decision by decision. Take the better choice per decision; do not average.

Requirements for your answer:
- `checks` must contain exactly one entry for every ledger item id: {{ledger_ids}}.
- `files` lists every path the implementation will create or modify; `check_files` lists where
  the acceptance checks will live (new files only).
- A `command` check must exit 0 only when its item holds; HTML deliverables are checked with
  `node tools/html-pages/check-page.mjs <file>` from the repo root.
- If an objection marked `changes_criterion` is right, put it in `criterion_disputes`; a person
  will decide. Do not paper over it.
- `notes`: what the implementer most needs to know.

<proposals>
{{proposals}}
</proposals>

<objections>
{{objections}}
</objections>

{{feedback}}
