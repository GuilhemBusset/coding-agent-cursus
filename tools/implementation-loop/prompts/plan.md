Plan this issue. {{branch_note}}

For **every** ledger item ({{ledger_ids}}) return one entry:
- `reading`: how you read it, and `quote`: words copied from the item that your reading relies on.
- `proof`, one of:
  - `test`: a durable test you will commit (pytest through uv, or node:test for the HTML tooling);
  - `command`: a one-shot command whose recorded output proves it (for example
    `node tools/html-pages/check-page.mjs <file>` for an HTML page);
  - `review`: the examiner judges it from the result (prose, teaching quality, visuals, facts);
  - `owner`: only when it needs a capability this host lacks ({{lacks}}). Give that `capability`
    exactly, and the `agent_part`: what agents still build and prove (or `none`, with why);
  - `deferred`: only when it needs another **open** issue's deliverable. Give `depends_on` and
    `depends_quote`, words from that issue's title or body that show it delivers what you need.
- `zones`: every path you expect to change, registrations and test files included. A path outside
  the issue's session folder or under `tools/implementation-loop/`, `.github/` or `.githooks/` needs
  the examiner's approval later; plan around it if you can.
- `decisions`: the choices that matter, each with its rationale. They are published in the PR.

Keep it proportional: the smallest correct plan that delivers every item as written.

{{feedback}}
