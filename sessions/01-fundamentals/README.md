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

The pre-work tests (`tests/test_prework.py`) also run the student-facing `check-setup.ps1` under
PowerShell 7, and fail rather than skip without it. On Linux, install the pinned PowerShell once
from the repo root with `bash setup/pwsh.sh`, which links it as `~/.local/bin/pwsh` (keep that
directory on `PATH`, or set `CURSUS_PWSH`). The whole suite takes about 15 minutes, 12 of them in
four scenarios that wait out the check's 180 s agent timeout; add `-k "not smoke_timeout"` for a
quick run. `tests/prework_live_agents.py` is not collected by
`uv run pytest`: run it by hand with `uv run python tests/prework_live_agents.py` to repeat the
live proof that the check passes with only Claude Code and with only Codex. It needs both agents
installed and logged in, and costs one short prompt to each.

`uv sync` installs only the runtime dependencies (`pytest`, `highspy`, `numpy`) into this
session's `.venv/`, at the versions pinned in `uv.lock`. The `fixtures` dependency group
(`torch`, `transformers`) is for building the files in `cursus/fixtures/` only. Students never
need it; instructors who rebuild fixtures opt in with `uv sync --group fixtures`.

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
| `exercises/00-prework.html` | Pre-work page: install steps for git, gh, uv, mise and Claude Code or Codex on macOS, Linux, WSL and Windows, login troubleshooting, the setup check and the pre-reading |
| `exercises/check-setup.sh`, `exercises/check-setup.ps1`, `exercises/check_setup.py` | The students' setup check: Bash and PowerShell wrappers around one stdlib Python core, run through uv. PASS or FAIL per tool, network, `gh` login, a push to a temporary `setup-check/<handle>` branch, an agent smoke test, then a summary block to paste |
| `prework-verification.md` | Evidence for the pre-work: install and reading sources with the date checked, platform status, recorded runs. Kept outside `exercises/` so it never lands in homework branches |
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
