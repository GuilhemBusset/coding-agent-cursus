Propose a design for this issue. You are proposer {{author}}; another agent proposes
independently and you will not see each other's work. Priority for your proposal: **{{lens}}**.

Read the code and documents the issue depends on before deciding. Then return:
- `decisions`: the choices that matter (id, choice, rationale).
- `files`: every repo-relative path the implementation will create or modify.
- `check_files`: where new acceptance checks will live (new files only, normally under the
  session's `tests/` folder). Use the test runner that fits the deliverable: pytest through uv
  for Python (`uv run --no-project --with pytest==8.3.5 pytest ...`; there may be no bare
  `python`), node:test for the HTML tooling. Leave it empty if existing tools prove every item.
- `checks`: one entry per ledger item id ({{ledger_ids}}), saying how that item is proven:
  - `command`: an exact shell command and the directory to run it from (repo-relative `cwd`).
    It must exit 0 only when the item holds. For every HTML deliverable,
    include `node tools/html-pages/check-page.mjs <file>` run from the repo root.
  - `artifact`: something a reviewer must judge from evidence (teaching quality, visuals).
  - `manual`: only for things no agent can do (a timed rehearsal with people, another
    person's account, a real-world recording). Never use it to avoid work.
- `open_questions`: anything the issue leaves genuinely ambiguous, with the reading you chose.
  Nobody will be asked during the run; the judge decides.

{{feedback}}
