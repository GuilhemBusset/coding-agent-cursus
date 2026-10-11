# Sampling divergence · runbook

One pass of a model gives a probability distribution over the next token, not an answer. The
answer is drawn from it, and `temperature` sets how flat that distribution is. Send one prompt five
times at a low and five times at a high temperature through the API and count the distinct
answers. The prompt is fixed in `sampling.py`: "Invent a name for a new optimization solver.
Reply with the name only." (20 tokens at most, no `top_p`, no extended thinking).

**Status: recording pending.** The run that built this demo had no API key, so there is no
`recorded/sampling.json` yet. Record one before class (step 3 below). Until then the only offline
option is the GPT-2 [stand-in](#offline-stand-in-gpt-2-next-token), which is not the API.

## Before class

1. Export a key: `export ANTHROPIC_API_KEY=…` (or `OPENAI_API_KEY` with `--provider openai`).
   The script reads it from the environment only and stops with a one-line message if it is
   unset or blank. It is sent in the auth header and never printed or recorded.
2. Rehearse once from this folder (see [Run](#run)).
3. Record the fallback with `uv run sampling.py --provider anthropic --record`, then fill in
   [Expected outcome](#expected-outcome) and [Recorded runs](#recorded-runs) and commit all three.

## Temperature support

As of 2026-10-11, from the vendors' API references (not from a live call). Anthropic deprecates
`temperature` for its newer models: "Models released after Claude Opus 4.6 do not support setting
temperature. A value of 1.0 will be accepted for backwards compatibility, all other values will be
rejected with a 400 error." The defaults in `sampling.py` are models that still accept it.

| Model | Accepts `temperature`? | Range | Source |
| --- | --- | --- | --- |
| `claude-opus-4-6` (Anthropic default) | Yes; active, retirement not before 2027-02-05 | 0.0 to 1.0 | [Messages API][anthropic-messages], [deprecations][anthropic-deprecations] |
| `claude-opus-4-5-20251101`, `claude-haiku-4-5-20251001` | Yes; retirement possible from 2026-11-24 and 2026-10-15 | 0.0 to 1.0 | [Messages API][anthropic-messages], [deprecations][anthropic-deprecations] |
| Claude 4.7 and later, e.g. `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5` | No: only 1.0 is accepted, any other value returns a 400 error | 1.0 only | [Messages API][anthropic-messages], [deprecations][anthropic-deprecations] |
| `gpt-4.1-mini` (OpenAI default) | Yes; a model "without a reasoning step", not on the shutdown list | 0 to 2 | [Chat Completions][openai-chat], [model page][openai-model], [deprecations][openai-deprecations] |
| `gpt-6-*`, `gpt-5.6-*` (reasoning models) | Not stated on the pages cited; not used here | n/a | [Chat Completions][openai-chat] |

[anthropic-messages]: https://platform.claude.com/docs/en/api/messages/create
[anthropic-deprecations]: https://platform.claude.com/docs/en/about-claude/model-deprecations
[openai-chat]: https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
[openai-model]: https://developers.openai.com/api/docs/models/gpt-4.1-mini
[openai-deprecations]: https://developers.openai.com/api/docs/deprecations

Change a default only with this table. `--low 0.0 --high 1.0` sit inside both documented ranges.

## Timing

| Beat | Duration |
| --- | --- |
| Predict question, show of hands | 0:45 |
| Live run: ten short API calls | 0:30 |
| Read the two columns and the distinct counts | 1:15 |
| Link to the sampler lab and System 1 | 0:30 |
| **Total** | **3:00** |

## Predict

Ask: "Same prompt, same model, five times at temperature 0. How many different names do we get?
And five times at temperature 1?" Take a show of hands for 1, 2–3 and 4–5 in each case.

## Run

From this folder (`sessions/01-fundamentals/cursus/demos/model`), with a key exported:

```sh
uv run sampling.py                     # Anthropic, claude-opus-4-6
uv run sampling.py --provider openai   # OpenAI, gpt-4.1-mini
```

`--model`, `--low` and `--high` change the defaults. The script prints five rows of
`low | high` answers, then `distinct answers at temperature 0.0: k of 5` and the same for 1.0.

## Expected outcome

Observed counts: pending until `recorded/sampling.json` is recorded with a key. Usually several
distinct names at the high temperature and one or two at the low one, but this is not guaranteed:
sampling is not deterministic, the vendors document that even temperature 0 is not fully
deterministic, and a short creative prompt can repeat a favourite name at any temperature. Report
the counts you see, whichever way they fall, and tie them to the distribution in the sampler lab.

## Fallback

No key, no network or a vendor error: the script prints one line and stops. Replay the committed
recording instead. It needs no key and opens no socket.

```sh
uv run --offline sampling.py --replay
```

Until the recording exists, this prints one line: it is missing, how to make it, and the stand-in.

## Offline stand-in: GPT-2 next token

Not the API demo and not a recording. It draws GPT-2's next token after "The best thing about
learning is" five times at each temperature from softmax(z / T), argmax at T = 0, using the
committed logits in `cursus/fixtures/next_token.json`: model `openai-community/gpt2`, revision
`607a30d783dfa663caf39e06633721c8d4cfcd7e`, built 2026-10-10. No key, no network, writes nothing.

```sh
uv run --offline sampling.py --fixture
```

The fixture keeps the top 20 tokens only, so draws are renormalised over them; they hold 77.7% of
the full-vocabulary probability at T = 1. With the default seed 2026 the room sees `' that'` five
times on the left and three tokens on the right: `distinct answers at temperature 0.0: 1 of 5`,
`distinct answers at temperature 1.0: 3 of 5`. `--seed N` gives other draws, reproducibly.

## Recorded runs

| File | Provider | Model | Run date |
| --- | --- | --- | --- |
| `recorded/sampling.json` | pending: record with a key | — | — |

## Reset

From this folder. It restores the folder to the last commit and deletes `work/` and anything an
agent left here, so commit a new recording before you reset.

```sh
git restore --source=HEAD --staged --worktree -- . && git clean -fdx -- .
```
