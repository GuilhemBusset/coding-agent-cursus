Propose a design for this issue. You are proposer {{author}}; another agent proposes
independently and you will not see each other's work. Priority for your proposal: **{{lens}}**.

Read the code and documents the issue depends on before deciding. Then return:
- `decisions`: the choices that matter (id, choice, rationale).
- `files`: every repo-relative path the implementation will create or modify.
- `check_files`: where the acceptance checks will live (new files only, normally under the
  session's `tests/` folder). Prefer pytest test files.
- `checks`: one entry per ledger item id ({{ledger_ids}}), saying how that item is proven:
  - `command`: an exact shell command and the directory to run it from (repo-relative `cwd`).
    It must exit 0 only when the item holds. Use pytest for tests. For every HTML deliverable,
    include `node tools/html-pages/check-page.mjs <file>` run from the repo root.
  - `artifact`: something a reviewer must judge from evidence (teaching quality, visuals).
  - `manual`: only for things no agent can do (a timed rehearsal with people, another
    person's account, a real-world recording). Never use it to avoid work.
- `open_questions`: anything the issue leaves genuinely ambiguous.

{{feedback}}
