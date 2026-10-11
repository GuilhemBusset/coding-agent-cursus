# Act I demos · the model itself

**Instructor material.** Two short live demos for Act I of Session 1, each with a one-page
runbook, a stdlib `uv run` script and a dated recording that replays without a network. Like
every demo, they run on the instructor's Linux machine only (ADR 0010). Students do not run them.

| Demo | Runbook | Script | What the room sees |
| --- | --- | --- | --- |
| Strawberry pivot | [`strawberry.md`](strawberry.md) | [`strawberry.py`](strawberry.py) | A fast model, tools off, miscounts the r's in a 300-letter invented word; the same agent writes and runs code and gets 146 |
| Sampling divergence | [`sampling.md`](sampling.md) | [`sampling.py`](sampling.py) | One prompt sent five times at a low and five times at a high temperature, and how many distinct answers each gives |

[`recorded/`](recorded/) holds the dated recordings, each made by the script's `--record` and
never edited by hand:

- Strawberry: the naive answers and the pivot transcript for Claude Code and for Codex, and the
  `count_r.py` each agent wrote. Recorded on 2026-10-11.
- Sampling: **pending**. `recorded/sampling.json` needs an `ANTHROPIC_API_KEY` or
  `OPENAI_API_KEY`, which the run that built this demo did not have. Until someone with a key
  records it (see [`sampling.md`](sampling.md), Recorded runs), the sampling demo has no offline
  fallback.

Keys: `sampling.py` reads `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` from the environment, puts it in
the auth header only, and stops with a one-line message if it is unset. `strawberry.py` reads no
key: it drives the `claude` and `codex` CLIs, which use your own login. `--replay` needs neither.

Recordings keep only what the room needs: answers, tool calls, their output and the model
usage. Session and thread IDs are dropped, and paths are made relative to this folder or `~`.

Agents write to `work/` in this folder. It is not tracked, and each runbook's reset removes it.
