# Session 1 · Fundamentals

This session is self-contained ([ADR 0001](../../docs/adr/0001-self-contained-per-session-subfolders.md)):
it has its own `pyproject.toml`, `uv.lock`, `mise.toml`, test suite and this runbook. Nothing it
needs at runtime comes from elsewhere in the repository. Every command below is plain shell, so
it works the same whether you use Claude Code or Codex.

## Setup

Prerequisites: [mise](https://mise.jdx.dev/getting-started.html) and Bash (Git Bash on
Windows). mise installs the pinned Python 3.12 and uv from `mise.toml`.

From the repo root, run the setup helper:

```sh
bash setup/session-01-fundamentals.sh
```

From any other directory, pass the helper's path instead, for example
`bash ../../setup/session-01-fundamentals.sh` from inside this session. The helper resolves
the session from its own location, then runs `mise trust mise.toml`, `mise install` and
`uv sync --locked` (through `mise exec`) inside `sessions/01-fundamentals/`.

To do the same by hand, inside this directory:

```sh
mise trust
mise install
uv sync
```

Then run the session's tests:

```sh
uv run pytest
```

`uv sync` installs only the runtime dependencies (`pytest`, `highspy`, `numpy`) into this
session's `.venv/`, at the versions pinned in `uv.lock`. The `fixtures` dependency group
(`torch`, `transformers`) is for building the files in `cursus/fixtures/` only. Students never
need it, and `uv sync` never installs torch. Instructors who rebuild fixtures opt in per command
with `uv run --group fixtures` (see [Regenerating fixtures](#regenerating-fixtures)).

## Regenerating fixtures

The Act I labs read real model traces from `cursus/fixtures/`: `next_token.json` (GPT-2 small,
top-20 next-token logits for 20 prompts), `attention.json` (every GPT-2 attention layer and
head on one coreference sentence) and `base_vs_instruct.json` (greedy completions from
SmolLM2-135M base and instruct). They are committed, so nobody needs to rebuild them to teach.
To rebuild them (instructors only, Linux), run from this directory:

```sh
uv run --locked --group fixtures python cursus/fixtures/build_fixtures.py
```

- The first run needs network. On Linux x86_64 the locked torch wheel pulls large CUDA
  packages, and the models download to `~/.cache/huggingface`. The build itself runs on CPU
  and takes under a minute.
- Model revisions and the export date are pinned in `REVISIONS` and `EXPORT_DATE` at the top of
  the script. Bump them together to move to newer models, then commit the new JSON.
- The output is byte-identical across runs (CPU float32, one thread, greedy decoding, logits
  rounded to 3 decimals, attention quantized to 0–255). After a rebuild with unchanged pins,
  `git status` must be clean. This holds on Linux x86_64 with the locked libraries; a different
  CPU or BLAS could in theory flip a value that sits on a rounding boundary.
- To check that the committed JSON is real output from the pinned models (offline, after one
  build has filled the cache):
  `uv run --locked --group fixtures pytest -q -p no:cacheprovider tests/fixture_replay_checks.py`.
  The plain `uv run pytest` suite checks the schema and the 500 KB size limit without torch.

## Opening pages

Pages are plain HTML files that work offline. Double-click one, or open its `file://` path in a
browser (for example `file:///path/to/repo/sessions/01-fundamentals/cursus/labs/<page>.html`).
No server, CDN or network access is needed.

## Validating pages

Every page in this session declares `data-design-system="cursus"` and a `data-page-kind` of
`page`, `deck` or `lab`. Validation uses the repository's HTML tooling, which needs a one-time
`node setup/html-pages.mjs` (see [`setup/README.md`](../../setup/README.md)). Run both
commands from the repo root.

To check every page marked `data-design-system="cursus"` in the repository:

```sh
npm --prefix setup run check-repo
```

To check one page, pass its path:

```sh
node tools/html-pages/check-page.mjs sessions/01-fundamentals/cursus/labs/<page>.html
```

`uv run pytest` in this session also checks, without Node, that every page here carries those
markers and loads no remote resource. Plain outbound reading links are fine.

## Layout

| Path | Purpose |
| --- | --- |
| `cursus/` | The part taught in the room |
| `cursus/labs/` | Hands-on labs run during the session |
| `cursus/demos/` | Live demos shown by the instructor |
| `cursus/demos/cold-open/` | The cold open: an agent turns a word problem into an LP, solves it on HiGHS and prints a duality certificate. Runbook, problem, prompt, timed rehearsal, recorded fallback and a one-line reset |
| `cursus/fixtures/` | Prebuilt data the labs and demos load |
| `exercises/` | Offline work: pre-work before the session and home exercises after it |
| `exercises/p00-lab/` | P00, a seeded fixed-charge transport mini-pack: model, independent checker, contract tests and `export.py` for standalone lab copies |
| `exercises/l3-word-problem/` | L3, a weekly staffing MILP to model from a word problem: statement, data, the solution-file format, an independent stdlib checker (`check.py`) and three seeded wrong solutions |
| `tests/` | The session's pytest suite |

The boundary between `cursus/` and `exercises/` is load-bearing: `cursus/` holds only what is
taught live, and `exercises/` holds only what students do on their own time.

## Agenda

Placeholder: TBD — filled in by the Delivery hub issue.

| Time | Block | Material |
| --- | --- | --- |
| TBD | TBD | TBD |
