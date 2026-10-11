# Act I demos · the model itself

**Instructor material.** Two short live demos for Act I of Session 1, each with a one-page
runbook, a stdlib `uv run` script and dated recordings that replay without a network. Like
every demo, they run on the instructor's Linux machine only (ADR 0010). Students do not run them.

| Demo | Runbook | Script | What the room sees |
| --- | --- | --- | --- |
| Strawberry pivot | [`strawberry.md`](strawberry.md) | [`strawberry.py`](strawberry.py) | A fast model, tools off, miscounts the r's in a 300-letter invented word; the same agent writes and runs code and gets 146 |
| Sampling divergence | [`sampling.md`](sampling.md) | [`sampling.py`](sampling.py) | One prompt sent five times at the CLI's default sampling, and how many distinct answers come back |

Both scripts drive the coding-agent CLI you already have, Claude Code (`claude -p`) or Codex
(`codex exec`), through its own login. No script reads an API key or calls a provider API.
[`agent_cli.py`](agent_cli.py) holds the shared part: which CLI to use, the headless call and
what a recording keeps.

Which CLI: with no flag, the first one installed and logged in, in the order claude then codex;
the script prints which it picked. `--via claude` or `--via codex` forces one, and then the other
is never contacted. Logins are checked with `claude auth status` and `codex login status`. When
none is usable, the script stops with a message naming each CLI, whether it is missing or logged
out, how to log in (run `claude` and type /login, or run `codex login`), and its own `--replay`
command. `--replay` starts no CLI and opens no socket; with no `--via` it replays the Claude Code
recording.

[`recorded/`](recorded/) holds the recordings, each made by the script's `--record` on
2026-10-11 and never edited by hand. Each runbook's Recorded runs table gives the CLI version
and the model as the CLI reported it.

- `strawberry-claude.json`, `strawberry-codex.json`: the five tool-free answers of the ask step.
- `pivot-claude.json`, `pivot-codex.json`: the pivot's tool calls and their output.
- `claude_count_r.py`, `codex_count_r.py`: the `work/count_r.py` each agent wrote in the pivot.
- `sampling-claude.json`, `sampling-codex.json`: the five answers of the sampling demo.

Recordings keep only what the room and the evidence need: answers, tool calls and their output,
the model usage or Codex's config banner. Session and thread IDs are dropped, and paths are made
relative to this folder or `~`.

Agents write to `work/` in this folder. It is not tracked, and each runbook's reset removes it.
