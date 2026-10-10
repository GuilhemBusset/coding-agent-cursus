# Strawberry pivot · runbook

A model reads tokens, not letters, so counting the r's in a word is a guess dressed as an answer.
Ask a fast model, run headless with every tool withheld, how many r's are in a 401-letter
invented word, five times. Then ask the same model to write and run code. Works in Claude Code
and in Codex. The word is the `WORD` constant in [`strawberry.py`](strawberry.py) (205 r's).

## Before class

1. Set up the session once (`uv sync --locked` in `sessions/01-fundamentals/`). The pivot's
   `uv run` needs the session's `.venv/`, because Codex's sandbox has no network.
2. Check the CLI and your login: `claude --version` or `codex --version`, then a one-line prompt.
   The naive step uses each CLI's small model (`haiku`, `gpt-6-luna`); make sure yours offers it.
3. Rehearse once from this folder, then run the [reset](#reset).

## Timing

| Beat | Duration |
| --- | --- |
| Show the word, predict question, votes | 0:45 |
| Naive step, five answers (Claude Code ~1:50, Codex ~0:20) | 1:50 |
| Pivot command: the agent writes `work/count_r.py` and runs it | 0:45 |
| Tokens, not letters; link to the tokenizer lab | 0:40 |
| **Total** | **4:00** |

## Predict

Show the word, then ask: "The model writes fluent code and prose. Asked five times how many r's
this word has, will it get it right? Every time, close but off, or all over the place?" Take a
show of hands before you press Enter.

## Expected outcome

Recorded on 2026-10-10, first attempt of this configuration. The true count is 205.

- **Claude Code** (`claude-haiku-5-5`, effort `low`): wrong in 4 of 5 (205, 204, 210, 165, 206).
- **Codex** (`gpt-6-luna`, reasoning effort `low`): wrong in 5 of 5 (213, 156, 145, 173, 140).
- **Pivot**: both agents wrote a two-line `work/count_r.py`, ran `uv run python work/count_r.py`
  and printed `205` (the Codex transcript is attempt 2: attempt 1, without `--json`, gave the
  same `205` but kept no tool events). Claude added that it had copied the word by hand, so a copying slip would
  change the count. That is the next lesson: the code is checkable, and the copy is not.

An unrecorded timing rehearsal the same day gave 4 of 5 and 5 of 5 wrong again. Be ready for
the opposite too: the CLIs' default models, which think before answering (`claude-opus-5-5`,
`gpt-6-astra` at `xhigh`), counted this word right 10 times out of 10, and shorter words (29, 70
and 120 letters) right in every trial. Spelling a word out in a hidden reasoning trace is the
same pivot, done invisibly. If the room sees correct answers, say so and make that point.

## Run

From this folder (`sessions/01-fundamentals/cursus/demos/model/`). Naive step, five headless
runs, tools withheld (`--tools ""` for Claude Code, `--sandbox read-only` for Codex):

```sh
uv run --no-project python strawberry.py
uv run --no-project python strawberry.py --via codex
```

The pivot, same model. `strawberry.py --print-prompts` prints these prompts, word filled in.

```sh
claude -p "Write work/count_r.py that counts the letter r in strawberrbrarorrfurrrrieturrparrrrinderrderrorrfurrbrarrrinrroarderrquarrberrwerrverrrasorrbrarverwerrderrwerrtorrtorrrrierrumrrievererrriederrturrorrrrrrraberrberrtorrwerrquarrorrrrumrrieverbrarrrumsorrparrrrawerrtorrderrbrarersorrarerfurrrrrparrmirrbrarorrrrumerverbrarwerrfurrquarrbrarverrrarrierrierrierrofurrorrsorrverlerrparrtorrsorrerrrinrrrararrrumderrarorrerkirrturrrrinrraorrquarrbrarverparr and prints only the count. Run it with exactly this command: uv run python work/count_r.py and report what it prints." --model haiku --effort low --permission-mode acceptEdits --allowedTools "Bash(uv run:*)" --output-format stream-json --verbose
```

```sh
UV_CACHE_DIR="$PWD/work/.uv-cache" codex exec --json -m gpt-6-luna -c 'model_reasoning_effort="low"' --sandbox workspace-write "Write work/count_r.py that counts the letter r in strawberrbrarorrfurrrrieturrparrrrinderrderrorrfurrbrarrrinrroarderrquarrberrwerrverrrasorrbrarverwerrderrwerrtorrtorrrrierrumrrievererrriederrturrorrrrrrraberrberrtorrwerrquarrorrrrumrrieverbrarrrumsorrparrrrawerrtorrderrbrarersorrarerfurrrrrparrmirrbrarorrrrumerverbrarwerrfurrquarrbrarverrrarrierrierrierrofurrorrsorrverlerrparrtorrsorrerrrinrrrararrrumderrarorrerkirrturrrrinrraorrquarrbrarverparr and prints only the count. Run it with exactly this command: uv run python work/count_r.py and report what it prints." < /dev/null
```

The flags are the cold open's (`--permission-mode acceptEdits` and only `uv run` for Claude
Code; `workspace-write` and a uv cache under `work/` for Codex). Both stream JSON events, so the
room sees each tool call and its output as it happens. `--via anthropic|openai` sends
the naive question straight to the API instead, using `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.

## Fallback

Dead network, exhausted quota or a broken login: replay the recordings. No CLI, key or socket.

```sh
cd "$(git rev-parse --show-toplevel)/sessions/01-fundamentals/cursus/demos/model"
uv run --no-project --offline python strawberry.py --replay
uv run --no-project --offline python strawberry.py --replay --via codex
```

They print [`strawberry-claude.json`](recorded/strawberry-claude.json) and
[`strawberry-codex.json`](recorded/strawberry-codex.json). For the pivot, scroll through
[`claude-pivot.txt`](recorded/claude-pivot.txt) or [`codex-pivot.txt`](recorded/codex-pivot.txt),
then run the code the agent wrote: `uv run --offline python recorded/claude_count_r.py` prints 205.

## Recorded runs

| Recording | Model | Run date | Attempt |
| --- | --- | --- | --- |
| [`strawberry-claude.json`](recorded/strawberry-claude.json) | claude-haiku-5-5 | 2026-10-10 | 1 |
| [`strawberry-codex.json`](recorded/strawberry-codex.json) | gpt-6-luna | 2026-10-10 | 1 |
| [`claude-pivot.txt`](recorded/claude-pivot.txt), [`claude_count_r.py`](recorded/claude_count_r.py) | claude-haiku-5-5 | 2026-10-10 | 1 |
| [`codex-pivot.txt`](recorded/codex-pivot.txt), [`codex_count_r.py`](recorded/codex_count_r.py) | gpt-6-luna | 2026-10-10 | 2 |

## Reset

One command, from anywhere in the repository. It restores this folder to the committed state and
deletes `work/`, its uv cache and anything else an agent left here. Commit your own edits first.

```sh
git -C "$(git rev-parse --show-toplevel)" restore --source=HEAD --staged --worktree -- sessions/01-fundamentals/cursus/demos/model && git -C "$(git rev-parse --show-toplevel)" clean -fdx -- sessions/01-fundamentals/cursus/demos/model
```
