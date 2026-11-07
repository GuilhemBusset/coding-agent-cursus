# Session 1 · Fundamentals

This session is self-contained ([ADR 0001](../../docs/adr/0001-self-contained-per-session-subfolders.md)):
it has its own `pyproject.toml`, `uv.lock`, `mise.toml`, test suite and this runbook. Nothing it
needs at runtime comes from elsewhere in the repository. Every command below is plain shell, so
it works the same whether you use Claude Code or Codex.

## Setup

Students: the one-command [student setup](../../setup/student/README.md) installs the tools,
clones the course and does this step for you.

Prerequisites: [mise](https://mise.jdx.dev/getting-started.html), uv and Bash (Git Bash on
Windows). mise installs the pinned Python 3.12 and uv from `mise.toml`.

From the repo root, run the setup helper:

```sh
bash setup/session-01-fundamentals.sh
```

From any other directory, pass the helper's path instead, for example
`bash ../../setup/session-01-fundamentals.sh` from inside this session. The helper resolves
the repository from its own location, activates the git hooks, then runs `mise trust mise.toml`,
`mise install` and `uv sync --locked` (through `mise exec`) inside `sessions/01-fundamentals/`
and every other session folder that has a `mise.toml`, `pyproject.toml` and `uv.lock`.
It also prepares the repository tools and installs the pinned VS Code extensions when VS Code's
`code` CLI is available. Open `setup/cursus.code-workspace` from the repository root for the whole
course, or open this session folder on its own; the checked-in settings select the local Python
environment and ty automatically. See [editor setup](../../setup/README.md#vs-code).

To install this session's Python environment by hand, inside this directory:

```sh
mise trust
mise install
uv sync
```

Then run the session's tests. They come in two parts, which follow the line between `cursus/`
and `exercises/` (see [Layout](#layout)):

| Part | Tests | Covers |
| --- | --- | --- |
| Lessons | `tests/lessons/` | What is taught live: the decks, the teaching labs, demos and fixtures in `cursus/`, and the hub `index.html` |
| Labs | `tests/labs/` | What students run: the pre-work check, the P00 and L3 labs, the lab ladder, the P01 homework and the turn-in gate in `exercises/`, and the editor setup their installation carries |

```sh
uv run pytest tests/lessons      # or tests/labs; plain `uv run pytest` runs both
```

To spread them over every core, as CI does, use the `parallel` dependency group (pytest-xdist),
which `uv sync` does not install:

```sh
uv run --group parallel pytest -n auto tests/lessons tests/labs
```

The lessons' browser suites (`tests/lessons/*.test.mjs`) need the repository's HTML tooling, a
one-time `node setup/html-pages.mjs` (see [`setup/README.md`](../../setup/README.md)). Run them
from the repo root, one with `node tools/html-pages/tests/run-suite.mjs
sessions/01-fundamentals/tests/lessons/<name>.test.mjs` or all of them with `npm --prefix setup test`.

CI also type-checks the session's Python with [ty](https://docs.astral.sh/ty/), configured in
`pyproject.toml`'s `[tool.ty]` and pinned in the default `typecheck` dependency group:

```sh
uv run --locked ty check
```

The pre-work tests (`tests/labs/test_prework.py`) also run the student-facing `check-setup.ps1`
under PowerShell 7, and fail rather than skip without it. On Linux, install the pinned PowerShell
once from the repo root with `bash setup/pwsh.sh`, which links it as `~/.local/bin/pwsh` (keep that
directory on `PATH`, or set `CURSUS_PWSH`). The agent-timeout scenario shortens the check's 180 s
default to 1 s through `CHECK_SETUP_SMOKE_TIMEOUT`; the network timeout and the fork-lookup
retries are tested in-process, without waiting them out. `tests/labs/prework_live_agents.py` is
not collected by `uv run pytest`: run it by hand with `uv run python tests/labs/prework_live_agents.py`
to repeat the live proof that the check passes with only Claude Code and with only Codex. It needs
both agents installed and logged in, and costs one short prompt to each.

`uv sync` installs the runtime dependencies (`pytest`, `highspy`, `numpy`) and ty into this
session's `.venv/`, at the versions pinned in `uv.lock`. The editor and CI use that same checker;
later syncs keep it installed. The `fixtures` dependency group
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
  `uv run --locked --group fixtures pytest -q -p no:cacheprovider tests/lessons/fixture_replay_checks.py`.
  The plain `uv run pytest` suite checks the schema and the 500 KB size limit without torch.
- `cursus/labs/attention.html` embeds `attention.json` verbatim in its
  `<script id="attention-data">` block, so it opens over `file://` without a fetch. After a
  rebuild that changes `attention.json`, paste the new file contents into that block and set
  its `data-sha256` to the new file's `sha256sum`. `tests/lessons/test_attention_lab.py` fails
  until both match. Then rerun the lab's browser suite from the repository root, `node
  tools/html-pages/tests/run-suite.mjs sessions/01-fundamentals/tests/lessons/attention.test.mjs`.
- `cursus/labs/next-token.html` embeds `next_token.json` the same way, in its
  `<script id="next-token-data">` block, without the file's trailing newline. After a rebuild
  that changes `next_token.json`, paste the new contents there;
  `tests/lessons/next-token.test.mjs` fails until the two match.

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


## Layout

| Path | Purpose |
| --- | --- |
| `index.html` | The session hub and student entry point: the agenda, and every deck, lab and exercise linked in teaching order |
| `cursus/` | The part taught in the room |
| `cursus/run-of-show.html` | Instructor page: the four hours minute by minute, with mode, file, demo command, fallback and helper notes |
| `cursus/instructor-notes.html` | Instructor page: misconceptions and expected questions per act (starting from the 2025 primer's list), and every peer-instruction question with its answer |
| `cursus/labs/` | Hands-on labs run during the session |
| `cursus/demos/` | Live demos shown by the instructor |
| `cursus/demos/model/` | Two Act I demos about the model itself: the strawberry pivot (miscounting letters, then counting with code) and sampling divergence (one prompt five times through the installed CLI at its default sampling). Runbooks, stdlib `uv run` scripts and dated recordings for offline replay |
| `cursus/fixtures/` | Prebuilt data the labs and demos load |
| `cursus/sources.html` | The session bibliography, grouped by act, with the date each source was last read |
| `cursus/sources/fact-check.md` | The fact-check log: every dated claim, its primary source and what the pass of 2026-10-18 did with it |
| `exercises/` | Offline work: pre-work before the session and home exercises after it |
| `exercises/00-prework.html` | Pre-work page: install steps for git, gh, uv, mise and Claude Code or Codex on macOS, Linux, WSL and Windows, login troubleshooting, the setup check and the pre-reading |
| `exercises/check-setup.sh`, `exercises/check-setup.ps1`, `exercises/check_setup.py` | The students' setup check: Bash and PowerShell wrappers around one stdlib Python core, run through uv. PASS or FAIL per tool, network, `gh` login, a push to a temporary `setup-check/<handle>` branch, an agent smoke test, then a summary block to paste |
| `prework-verification.md` | Evidence for the pre-work: install and reading sources with the date checked, platform status, recorded runs. Kept outside `exercises/` so it never lands in homework branches |
| `exercises/p00-lab/` | P00, a seeded fixed-charge transport mini-pack: model, independent checker, contract tests and `export.py` for standalone lab copies |
| `exercises/mini-homework/` | The mini homework, done end to end in Act IV: a weekly staffing MILP to model from a word problem, with its statement, data, the five steps (read, plan, build, check, ship), the solution-file format and an independent stdlib checker (`check.py`), which the turn-in reruns |
| `exercises/home.html` | The homework sheet: rerun two demos, three sentences on "sampling, not retrieval", solve P01, turn in with `/turn-in 01` or `$turn-in 01`. Each part says what a good answer looks like, and the grading rule is that checker-proven feasibility counts more than the objective value. Students write their notes in `exercises/home-notes.md` |
| `exercises/homework-p01/` | P01, the take-home: EV linehaul scheduling and charging. Statement, revised data, an empty `p01_model.py` for the student's agent to build, an independent stdlib checker (`p01_checker.py`), the solve-contract suite (`p01_contract.py`) and instructor notes |
| `exercises/turn-in-check.sh` | The session's turn-in gate, run by `/turn-in 01`, `$turn-in 01` and `scripts/turn-in.sh 01`; it runs the mini homework's checker, then P01's, each with `--turn-in` |
| `tests/lessons/` | Tests of what is taught live (`cursus/`, `index.html`): pytest and the lessons' browser suites |
| `tests/labs/` | Tests of what students run (`exercises/`) |
| `tests/labs/fixtures/p01_upstream/` | The untouched 2025 P01 files and their MIT licence, pinned by hash, from which `exercises/homework-p01/data/` is derived |

The boundary between `cursus/` and `exercises/` is load-bearing: `cursus/` holds only what is
taught live, and `exercises/` holds only what students do on their own time.

## Agenda

Students start from [`index.html`](index.html), which links everything below in this order.
Times are hours and minutes from the start, from the Session 1 plan
(`docs/cursus-narrative.md`), as of 2026-11-05. The
instructor's minute-by-minute plan, with demo commands and fallbacks, is
[`cursus/run-of-show.html`](cursus/run-of-show.html).

| Time | Block | Material |
| --- | --- | --- |
| Before | Pre-work | [`exercises/00-prework.html`](exercises/00-prework.html) |
| 0:00–0:15 | Opening | Deck [`cursus/00-opening.html`](cursus/00-opening.html) |
| 0:15–1:00 | Act I · The sampler | Deck [`cursus/01-sampler.html`](cursus/01-sampler.html); labs [`tokenizer`](cursus/labs/tokenizer.html), [`attention`](cursus/labs/attention.html), [`next-token`](cursus/labs/next-token.html), [`tiny-lm`](cursus/labs/tiny-lm.html); demos [`cursus/demos/model/`](cursus/demos/model/README.md) |
| 1:00–1:10 | Break | |
| 1:10–1:50 | Act II · Thinking | Deck [`cursus/02-thinking.html`](cursus/02-thinking.html); labs [`test-time-compute`](cursus/labs/test-time-compute.html), [`world-model`](cursus/labs/world-model.html); demo [`cursus/demos/effort/`](cursus/demos/effort/README.md) |
| 1:50–2:35 | Act III · Agent = model + harness | Deck [`cursus/03-agent.html`](cursus/03-agent.html); labs [`context`](cursus/labs/context.html), [`agent-loop`](cursus/labs/agent-loop.html); demos [`cursus/demos/agent/`](cursus/demos/agent/README.md) |
| 2:35–2:45 | Break | |
| 2:45–3:55 | Act IV · Claim versus evidence | Deck [`cursus/04-evidence.html`](cursus/04-evidence.html); the mini homework, end to end and turned in ([`exercises/mini-homework/`](exercises/mini-homework/README.md)); lab [`verifier-gaming`](cursus/labs/verifier-gaming.html), optional, after class |
| 3:55–4:00 | Close | Deck [`cursus/99-close.html`](cursus/99-close.html): exit ticket and homework |
| After | Homework | [`exercises/home.html`](exercises/home.html) and P01, [`exercises/homework-p01/`](exercises/homework-p01/README.md); turn in with `/turn-in 01` or `$turn-in 01` |
