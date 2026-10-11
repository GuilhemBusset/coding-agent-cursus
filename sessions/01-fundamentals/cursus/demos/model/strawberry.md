# Strawberry pivot · runbook

A model reads tokens, not letters, so counting the r's in a long word is a guess. An agent that
writes and runs code does not guess. Show the guess failing, then the pivot to code. Works with
Claude Code or with Codex through the CLI's own login, no API key: the script uses the first one
installed and logged in (claude, then codex) and says which; `--via codex` or `--via claude`
forces one.

The word is a 300-letter invention with **146** r's, fixed in `strawberry.py` as `WORD` so
recordings stay comparable. The ask runs headless five times with tools off (`claude -p --tools ""`
or `codex exec --sandbox read-only` with the shell tool disabled) and asks for the number only.

## Before class

1. Log in to the CLI you will use: run `claude` and type /login, or run `codex login`.
2. Rehearse once from this folder (commands under [Run](#run)), then run the [reset](#reset).
3. Keep the [Fallback](#fallback) commands ready in a second terminal.

## Timing

| Beat | Duration |
| --- | --- |
| Show the word, predict question, show of hands | 0:45 |
| Live ask: five headless runs, tools off | 1:00 |
| Read the ✓ and ✗ against the true count | 0:30 |
| Live pivot: the agent writes and runs `work/count_r.py` | 1:15 |
| Debrief: tokens, not letters; hand the counting to code | 0:30 |
| **Total** | **4:00** |

## Predict

Show the word on screen. Ask: "I will ask the same model the same question five times, with no
tools. How many of the five answers will be the right count?" Take a show of hands for 0, 1–2,
3–4 and 5. Then: "And if it may write code?"

## Run

From this folder (`sessions/01-fundamentals/cursus/demos/model`):

```sh
uv run strawberry.py                     # ask, first installed and logged-in CLI
uv run strawberry.py --pivot             # pivot, same CLI
uv run strawberry.py --via codex         # ask, force Codex (or --via claude)
uv run strawberry.py --via codex --pivot # pivot, force Codex
```

With neither CLI installed or logged in, the script stops with a message saying which is missing
or logged out, how to log in, and the replay command.

The ask prints one line per run (`run 3: 128  ✗`) and a summary
(`wrong: 4 of 5 (unparseable: 0, tool-assisted: 0; true count: 146)`). A run flagged
`[tool used]` means the agent ran a tool despite the instruction; say so, it does not count. The
pivot prints each tool call with its output (Claude Code as `tool:` lines, Codex as its own
`exec` transcript), then `true count: 146`.

## Expected outcome

The true count is 146. Recorded on 2026-10-11, with tools off:

- Claude Code, `claude-haiku-5-5` at low effort: 118, 146, 146, 146, 142, so 2 of 5 wrong.
- Codex, `gpt-6-luna` at low reasoning effort: 138, 146, 128, 114, 133, so 4 of 5 wrong.

The answers move between runs and are wrong by up to 32. Models change, so a live run can do
better or worse than this. If all five live answers happen to be correct, say so, then replay
the recording (`uv run --offline strawberry.py --replay`) to show the wrong answers it captured,
and pivot anyway: the point is that a correct guess is still a guess.

In the pivot, the agent writes a two-line `work/count_r.py` (`WORD = "…"`,
`print(WORD.count("r"))`), runs `uv run --no-project python work/count_r.py` and gets 146 every
time. Codex may look around the folder first; Claude Code may try a combined shell command that
is refused before it writes the file. Both happened in the recordings.

## Fallback

No login, no network or a CLI error: the script prints a message ending with the replay command.
Replay the recordings instead. They open no socket and start no process.

```sh
uv run --offline strawberry.py --replay
uv run --offline strawberry.py --replay --via codex
uv run --offline strawberry.py --replay --pivot
uv run --offline strawberry.py --replay --pivot --via codex
uv run --no-project --offline python recorded/claude_count_r.py
uv run --no-project --offline python recorded/codex_count_r.py
```

The last two run the code each agent wrote. Both print 146.

## Recorded runs

Made with `uv run strawberry.py [--pivot] --via <cli> --record`, never edited by hand.

| File | Step | CLI and version | Model as reported | Run date |
| --- | --- | --- | --- | --- |
| [`recorded/strawberry-claude.json`](recorded/strawberry-claude.json) | ask | Claude Code 2.1.296 | `claude-haiku-5-5` | 2026-10-11 |
| [`recorded/pivot-claude.json`](recorded/pivot-claude.json) | pivot | Claude Code 2.1.296 | `claude-haiku-5-5` | 2026-10-11 |
| [`recorded/claude_count_r.py`](recorded/claude_count_r.py) | pivot | Claude Code 2.1.296 | `claude-haiku-5-5` | 2026-10-11 |
| [`recorded/strawberry-codex.json`](recorded/strawberry-codex.json) | ask | Codex 0.162.1 | `gpt-6-luna` | 2026-10-11 |
| [`recorded/pivot-codex.json`](recorded/pivot-codex.json) | pivot | Codex 0.162.1 | `gpt-6-luna` | 2026-10-11 |
| [`recorded/codex_count_r.py`](recorded/codex_count_r.py) | pivot | Codex 0.162.1 | `gpt-6-luna` | 2026-10-11 |

The model is the one the CLI reported, kept in the same file: Claude Code's `modelUsage` and
`message.model`, and Codex's `model:` banner line from its plain-mode transcript, kept verbatim in
`meta.model_evidence` (`codex exec --json` prints no model, so the Codex calls run in plain mode
and read the final message from `-o`).

## Reset

From this folder. It restores the folder to the last commit and deletes `work/` and anything an
agent left here, so commit a new recording before you reset.

```sh
git restore --source=HEAD --staged --worktree -- . && git clean -fdx -- .
```
