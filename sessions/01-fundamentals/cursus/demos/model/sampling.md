# Sampling divergence · runbook

One pass of a model gives a probability distribution over the next token, not an answer. The
answer is drawn from it. Send one prompt five times through the coding-agent CLI you already have
and count the distinct answers. The prompt is fixed in `sampling.py`: "Invent a name for a new
optimization solver. Reply with the name only." Each run is headless with tools off (`claude -p
--tools ""`, or `codex exec --sandbox read-only` with the shell tool disabled) on a small model at
low effort: `claude-haiku-5-5` or `gpt-6-luna`. No API key: the CLI uses its own login.

## Before class

1. Log in to the CLI you will use: run `claude` and type /login, or run `codex login`.
2. Rehearse once from this folder (see [Run](#run)). The script prints which CLI it picked.
3. Keep the [Fallback](#fallback) command ready in a second terminal.
4. The script pins a small model (`claude-haiku-5-5` for Claude Code, `gpt-6-luna` for Codex),
   which must be available on your account. A refused model can show up as a login error; if that
   happens, use the [Fallback](#fallback) replay.

## Why no temperature

As of 2026-10-11, neither CLI has a temperature setting. `claude --help` (Claude Code 2.1.296)
and `codex exec --help` (codex-cli 0.162.1) list no temperature, top-p or seed option, and
neither does the [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference) nor
the [Codex CLI reference](https://developers.openai.com/codex/cli/reference). So this demo shows
the spread at each CLI's default sampling, and `sampling.py` passes no sampling argument at all.

For what temperature does to the distribution, send the room to the
[next-token lab](../../labs/next-token.html): its temperature, top-k and top-p sliders reshape
GPT-2's real next-token distribution live.

## Timing

| Beat | Duration |
| --- | --- |
| Predict question, show of hands | 0:45 |
| Live run: five short headless calls | 0:30 |
| Read the five answers and the distinct count | 1:15 |
| Link to the next-token lab and System 1 | 0:30 |
| **Total** | **3:00** |

## Predict

Ask: "Same prompt, same model, same settings, five times. How many different names do we get?"
Take a show of hands for 1, 2–3 and 4–5.

## Run

From this folder (`sessions/01-fundamentals/cursus/demos/model`):

```sh
uv run sampling.py               # first installed and logged-in CLI: claude, then codex
uv run sampling.py --via codex   # force one when you have both
```

The script prints `run 1:` to `run 5:` with each answer, a tally of each distinct answer, then
`distinct answers: k of 5`. With neither CLI installed or logged in it stops with a message
saying which is missing or logged out, how to log in, and the replay command.

## Expected outcome

Recorded on 2026-10-11, the same prompt through each CLI:

- Claude Code, `claude-haiku-5-5`: Vantablend, Quorvex, Quillstep, Quillfathom, Gradientwhisk,
  so 5 of 5 distinct.
- Codex, `gpt-6-luna`: Fluxforge, Fluxora, OptiForge, Parallax Solver, OptiForge, so 4 of 5
  distinct (OptiForge twice).

Same input, different outputs: each answer is one draw from the distribution. A live run can
repeat a favourite name more often, or even five times. Report the count you get, whichever way
it falls, then replay the recording to show a run with spread and open the next-token lab to
show why: at the default temperature, several names keep real probability.

## Fallback

No login, no network or a CLI error: the script prints a message ending with the replay command.
Replay the committed recordings instead. They open no socket and start no process.

```sh
uv run --offline sampling.py --replay
uv run --offline sampling.py --replay --via codex
```

## Recorded runs

Made with `uv run sampling.py --via <cli> --record`, never edited by hand. The model is the one
the CLI reported: Claude Code's `modelUsage` in its JSON result, Codex's `model:` banner line,
kept in `meta.model_evidence`.

| File | CLI and version | Model as reported | Run date |
| --- | --- | --- | --- |
| [`recorded/sampling-claude.json`](recorded/sampling-claude.json) | Claude Code 2.1.296 | `claude-haiku-5-5` | 2026-10-11 |
| [`recorded/sampling-codex.json`](recorded/sampling-codex.json) | Codex 0.162.1 | `gpt-6-luna` | 2026-10-11 |

## Reset

From this folder. It restores the folder to the last commit and deletes `work/` and anything an
agent left here, so commit a new recording before you reset. It first checks that `strawberry.py`
and `sampling.py` are in the current directory, so it refuses to run anywhere but this folder.

```sh
test -f strawberry.py && test -f sampling.py && git restore --source=HEAD --staged --worktree -- . && git clean -fdx -- .
```
