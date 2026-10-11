# Strawberry pivot · runbook

A model reads tokens, not letters, so counting the r's in a long word is a guess. An agent that
writes and runs code does not guess. Show the guess failing, then the pivot to code. Works with
Claude Code or with Codex: pick the one you have (`--via claude` is the default).

The word is a 300-letter invention with **146** r's, fixed in `strawberry.py` as `WORD` so
recordings stay comparable. The ask runs headless five times with tools off (`claude -p --tools ""`
or `codex exec --sandbox read-only` with the shell tool disabled) and asks for the number only.

## Before class

1. Log in to the CLI you will use (`claude` or `codex`) and check it runs.
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
uv run strawberry.py                     # ask, Claude Code
uv run strawberry.py --pivot             # pivot, Claude Code
uv run strawberry.py --via codex         # ask, Codex
uv run strawberry.py --via codex --pivot # pivot, Codex
```

The ask prints one line per run (`run 3: 131  ✗`) and a summary
(`wrong: 5 of 5 (unparseable: 0, tool-assisted: 0; true count: 146)`). A run flagged
`[tool used]` means the agent ran a tool despite the instruction; say so, it does not count. The
pivot prints one `tool:` line per tool call with its output, then `true count: 146`.

## Expected outcome

The true count is 146. Recorded on 2026-10-11, with tools off:

- Claude Code, `claude-haiku-5-5` at low effort: 118, 146, 146, 146, 142, so 2 of 5 wrong.
- Codex, `gpt-6-luna` at low reasoning effort: 116, 86, 131, 129, 151, so 5 of 5 wrong.

The answers move between runs and are wrong by up to 60. Models change, so a live run can do
better or worse than this. If all five live answers happen to be correct, say so, then replay
the recording (`uv run --offline strawberry.py --replay`) to show the wrong answers it captured,
and pivot anyway: the point is that a correct guess is still a guess.

In the pivot, the agent writes a two-line `work/count_r.py` (`WORD = "…"`,
`print(WORD.count("r"))`), runs `uv run --no-project python work/count_r.py` and gets 146 every
time. Codex may look around the folder first; Claude Code may try a combined shell command that
is refused before it writes the file. Both happened in the recordings.

## Fallback

No login, no network or a CLI error: the script prints one line pointing here. Replay the
recordings instead. They open no socket and start no process.

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

| File | Step | CLI | Model | Run date |
| --- | --- | --- | --- | --- |
| [`recorded/strawberry-claude.json`](recorded/strawberry-claude.json) | ask | Claude Code 2.1.296 | `claude-haiku-5-5` | 2026-10-11 |
| [`recorded/pivot-claude.json`](recorded/pivot-claude.json) | pivot | Claude Code 2.1.296 | `claude-haiku-5-5` | 2026-10-11 |
| [`recorded/claude_count_r.py`](recorded/claude_count_r.py) | pivot | Claude Code 2.1.296 | `claude-haiku-5-5` | 2026-10-11 |
| [`recorded/strawberry-codex.json`](recorded/strawberry-codex.json) | ask | Codex 0.162.1 | `gpt-6-luna` | 2026-10-11 |
| [`recorded/pivot-codex.json`](recorded/pivot-codex.json) | pivot | Codex 0.162.1 | `gpt-6-luna` | 2026-10-11 |
| [`recorded/codex_count_r.py`](recorded/codex_count_r.py) | pivot | Codex 0.162.1 | `gpt-6-luna` | 2026-10-11 |

Claude Code reports the model it used (`modelUsage`). Codex does not, so its recordings repeat
the requested ID and say so in `meta.model_reported_note`.

## Reset

From this folder. It restores the folder to the last commit and deletes `work/` and anything an
agent left here, so commit a new recording before you reset.

```sh
git restore --source=HEAD --staged --worktree -- . && git clean -fdx -- .
```
