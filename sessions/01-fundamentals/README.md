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
| `cursus/fixtures/` | Prebuilt data the labs and demos load |
| `exercises/` | Offline work: pre-work before the session and home exercises after it |
| `tests/` | The session's pytest suite |

The boundary between `cursus/` and `exercises/` is load-bearing: `cursus/` holds only what is
taught live, and `exercises/` holds only what students do on their own time.

## Agenda

Placeholder: TBD — filled in by the Delivery hub issue.

| Time | Block | Material |
| --- | --- | --- |
| TBD | TBD | TBD |
