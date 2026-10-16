# Act III demos · the agent loop, plan first, and the context bomb

**Instructor material.** Three live demos for Act III of Session 1 ("Agent = model + harness"),
each with a one-page runbook, one reset command and dated recordings that replay without a CLI
or a network. Like every demo, they run on the instructor's Linux machine only (ADR 0010).
Students do not run them.

| Demo | Runbook | What the room sees |
| --- | --- | --- |
| The agent loop | [`loop.md`](loop.md) | On the flipped-sense P00, the agent reads `p00_model.py`, runs `uv run pytest`, sees red, fixes the objective sense, sees green. Once in Claude Code, once in Codex: same task, same prompt, swappable harness |
| Plan first vs straight to code | [`plan-first.md`](plan-first.md) | The same task twice on fresh exports: once straight to code, once as a read-only plan followed by a build. Tokens, tool calls, seconds, files changed and final pytest side by side |
| The context bomb | [`context-bomb.md`](context-bomb.md) | One noisy MCP server (a port of the 2025 workshop's) added to `claude -p "Reply with exactly: OK"`: `/context` before and after, the token cost with and without it, what tool search does about it, and the Codex equivalent |

Everything goes through one standard-library script, [`agent_demo.py`](agent_demo.py), run from
this folder (`sessions/01-fundamentals/cursus/demos/agent`):

```sh
uv run agent_demo.py reset loop                # the one reset command of each demo
uv run agent_demo.py run loop --via claude     # reset, then the demo live (--via is required)
uv run agent_demo.py replay loop --via codex   # the fallback: plays a recording, no CLI, no network
```

The script drives the CLI you name, Claude Code (`claude -p`) or Codex (`codex exec`), through
its own login. It reads no API key and calls no provider API. `--via` is required, so the
harness you show is always the one you chose.

## Where the demos work

Each demo works in `<tempdir>/cursus-s1-agent/<demo>/` (on Linux `/tmp/cursus-s1-agent/`),
outside the course checkout. `--work-root <dir>` moves it. `reset` only ever deletes that one
demo folder, and `run` always starts with the same reset:

- **loop** and **plan**: a fresh `flipped-sense` export of P00, made by
  [`exercises/p00-lab/export.py`](../../../exercises/p00-lab/README.md) (instructor notes there
  name the bug: `kMinimize` became `kMaximize`), then `uv sync --locked --offline` in the export.
  Clean means the same content as any fresh export, compared by file hashes, not commit IDs
  (`export.py` makes a new, time-stamped commit each time), and `uv run pytest` failing exactly
  `test_objective_contract`.
- **bomb**: a folder holding only `mcp.json`, which points at [`context_bomb.py`](context_bomb.py)
  in this folder. The server is passed per invocation (`--strict-mcp-config --mcp-config` for
  Claude Code, `-c mcp_servers.context_bomb.…` for Codex) and is never registered with
  `claude mcp add` or `codex mcp add`, so nothing outlives the call.

Agents run `uv run pytest` with `UV_OFFLINE=1 UV_NO_SYNC=1 UV_NO_CACHE=1`: the reset already
synced the export, and Codex's `workspace-write` sandbox cannot write uv's own cache.

## Before class

1. Warm the session's uv cache once, online: `uv sync` in `sessions/01-fundamentals`. After that,
   every reset is offline. If a reset cannot sync, it says so and prints the replay command.
2. Log in to both CLIs: run `claude` and type /login, and run `codex login`.
3. Rehearse each demo once with each CLI (the runbooks' Run sections), then reset.
4. Codex's TUI may offer an update when it starts. The script skips the offer so the recorded
   version stays the one in the tables; do the same by hand (press Esc).
5. Keep a second terminal open in this folder with the Fallback commands ready.

## Models and versions

| Demo | Claude Code | Codex | Effort |
| --- | --- | --- | --- |
| loop, plan | `claude-opus-5-5` | `gpt-6-astra` | medium |
| bomb | `claude-haiku-5-5` | `gpt-6-luna` | low |

Loop and plan use the models the lab-ladder rehearsal already proved on P00
([`lab-ladder-rehearsal.md`](../../labs/lab-ladder-rehearsal.md)), at medium effort instead of
that rehearsal's xhigh, because the room is waiting. The bomb only needs a one-word answer, so it
uses the small models of the Act I demos. The pins are constants at the top of `agent_demo.py`.

Every recording in [`recorded/`](recorded/) was made on 2026-10-16 with **Claude Code 2.1.301**
and **codex-cli 0.162.1**. The CLI version and the model (as the CLI reported it, or as requested
when the CLI's JSON names none, which is the case for `codex exec --json`) are in each runbook's
Recorded runs table and in each `*.meta.json`.

## Recordings

`uv run agent_demo.py run <demo> --via <cli> --record --run <N>` writes, for each rehearsal:

- `recorded/<demo>-<cli>-run<N>[-<arm>].jsonl`: the CLI's own stdout, one JSON event per line,
  exactly as `claude -p --output-format stream-json --verbose` or `codex exec --json` printed it
  (these are the inputs the agent-loop replay widget's normalizer will read). Only scrubbed: the
  home folder becomes `~`, the user name `<user>`, the account email `<account>`, the agent's own
  folder `.` (so a recorded plan still reads as relative paths) and the rest of the work root
  `<work>`; session, thread, message and request IDs become placeholders.
- `recorded/<demo>-<cli>-run<N>.meta.json`: the command line (the prompt as `<prompt>`, plus its
  sha256), CLI version, model and its provenance, effort, UTC start and end, exit codes, the
  token counters re-derived from the raw stream, and the full state before and after: sha256 of
  every file in the export, the script's own pytest exit code and failing test IDs, the diff's
  file list and the full text of `p00_model.py`.
- for the bomb, the `/context` (Claude Code) or `/status` (Codex) captures, before and after.

Each demo was rehearsed twice in a row with each CLI, with the reset between the two runs. No
recording is edited by hand. `uv run agent_demo.py replay …` reads them and prints the tool calls,
the red and green pytest lines and the token tables. Playback in the agent-loop replay widget
(`cursus/labs/agent-loop.html`) waits for that widget and its normalizer, which are separate
issues and are not in this folder.

## No proprietary solver

The demos use P00 as it is: HiGHS through `highspy` and the standard-library checker. Nothing in
this folder imports anything outside the Python standard library, and the export's lock file
names no commercial solver.
