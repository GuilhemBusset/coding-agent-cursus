# Act I demos · the model itself

**Instructor material.** Two short live demos for Act I of Session 1, each with a one-page
runbook, a stdlib `uv run` script and a dated recording that replays without a network. Like
every demo, they run on the instructor's Linux machine only (ADR 0010). Students do not run them.

| Demo | Runbook | Script | What the room sees |
| --- | --- | --- | --- |
| Strawberry pivot | [`strawberry.md`](strawberry.md) | [`strawberry.py`](strawberry.py) | A fast model miscounts the r's in a 401-letter invented word; the same model writes and runs code and gets 205 |
| Sampling divergence | [`sampling.md`](sampling.md) | [`sampling.py`](sampling.py) | One prompt sent five times at a low and five times at a high temperature, and how many distinct answers each gives |

| File | What it is |
| --- | --- |
| [`ask.txt`](ask.txt), [`pivot.txt`](pivot.txt) | The two strawberry prompts. `{WORD}` is filled in by `strawberry.py --print-prompts` |
| [`llm_api.py`](llm_api.py) | A stdlib client for the Anthropic and OpenAI APIs. Keys are read from the environment only |
| [`recorded/`](recorded/) | Dated recordings: naive answers, pivot transcripts and the code the agents wrote, and, once someone with an API key records them, the sampling run and an optional temperature probe |

Keys: `sampling.py` and the API modes of `strawberry.py` read `ANTHROPIC_API_KEY` or
`OPENAI_API_KEY` from the environment and stop with a one-line message if it is unset. The CLI
modes of `strawberry.py` use your Claude Code or Codex login instead. `--replay` needs neither.

Agents write to `work/` in this folder. It is not tracked, and each runbook's reset removes it.
