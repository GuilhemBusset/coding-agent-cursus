# Sampling divergence · runbook

One pass of a model gives a probability distribution over the next token, not an answer. The
answer is drawn from it, and `temperature` sets how flat that distribution is. Send one prompt five
times at a low and five times at a high temperature and count the distinct answers.

**Status (2026-10-10): not recorded yet.** The implementation run had no `ANTHROPIC_API_KEY` or
`OPENAI_API_KEY`, and a Claude Code or Codex login cannot set a temperature. The script and its
request shape are tested against a local stub server for both vendors, but there is no
`recorded/sampling.json` yet. Recording it is the first item of [Before class](#before-class).

## Before class

1. Set up the session once (`uv sync --locked` in `sessions/01-fundamentals/`).
2. Export a key: `export ANTHROPIC_API_KEY=…` (or `OPENAI_API_KEY`). The script reads it from the
   environment only and stops with a one-line message if it is unset or blank.
3. From this folder, record a run with the default model, which the
   [Temperature support](#temperature-support) table lists as accepting `temperature`:

   ```sh
   uv run --no-project python sampling.py --provider anthropic --record recorded/sampling.json
   ```

   With an OpenAI key, use `--provider openai` instead. Never edit a recording by hand. A new
   recording of the same configuration increments `meta.attempt`.
4. Optional: confirm the table against the live API. The probe asks each model once with a
   temperature and writes `recorded/temperature_probe.json`:

   ```sh
   uv run --no-project python sampling.py --probe --provider anthropic --model claude-opus-4-6 --model claude-haiku-4-5-20251001 --model claude-haiku-5-5
   ```

   For OpenAI, probe `gpt-4.1-mini` and two current reasoning models.
5. Edit this runbook to match: replace the status note above and the
   [Expected outcome](#expected-outcome) paragraph with the observed distinct counts and the
   attempt number, and turn each `Recorded runs` row into a link with the model and run date from
   the recording's `meta`. Commit the recordings together with these edits.
6. Rehearse once, then run the [reset](#reset).

## Temperature support

As of 2026-10-10, from the vendors' documentation, not from a live call. The Anthropic Messages
API reference says: "Models released after Claude Opus 4.6 do not support setting temperature. A
value of 1.0 will be accepted for backwards compatibility, all other values will be rejected with
a 400 error."

| Model | Accepts `temperature`? | Source |
| --- | --- | --- |
| `claude-opus-4-6` (Anthropic default here) | Yes, 0.0 to 1.0: the documented cut-off is "released after Claude Opus 4.6". Active, retirement not before 2027-02-05 | [Messages API](https://platform.claude.com/docs/en/api/messages), [deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) |
| `claude-haiku-4-5-20251001`, `claude-opus-4-5-20251101` | Yes, same rule. Retirement possible from 2026-10-15 and 2026-11-24 | same |
| `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-fable-5-1` | No: "a value of 1.0 will be accepted for backwards compatibility, all other values will be rejected with a 400 error" | [Messages API](https://platform.claude.com/docs/en/api/messages) |
| `gpt-4.1-mini` (OpenAI default here) | Yes per the Chat Completions reference (0 to 2); described as a model "without a reasoning step" | [Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [model page](https://developers.openai.com/api/docs/models/gpt-4.1-mini) |
| `gpt-6-*`, `gpt-5.6-*` (reasoning models) | Not stated on the pages above | same |

The defaults live in `llm_api.DEFAULT_MODELS`. Change one only together with this table. For any
other model, the optional probe in [Before class](#before-class) settles it.

## Timing

| Beat | Duration |
| --- | --- |
| Predict question, votes | 0:45 |
| Live run, ten short API calls | 0:30 |
| Read the two columns and the distinct counts | 1:15 |
| Link to the sampler lab and System 1 | 0:30 |
| **Total** | **3:00** |

## Predict

Before running, ask: "Same prompt, same model, five times at temperature 0. How many different
names do we get? And at temperature 1?" Take a show of hands for 1, 2–3 and 4–5 in each case.

## Expected outcome

Expected, not yet observed: several distinct names at the high temperature. At the low
temperature, mostly or all the same name, but identical answers are not guaranteed: the vendors
document that even temperature 0 is not fully deterministic, so a second name may still appear.
The observed counts get filled in from `recorded/sampling.json` once someone with a key records it
(see [Before class](#before-class)).

## Run

From this folder, with a key exported:

```sh
uv run --no-project python sampling.py --provider anthropic
```

`--provider openai`, `--model`, `--low` and `--high` change the defaults (`--low 0.0 --high 1.0`).
The script prints the two columns side by side, then `distinct outputs: …` for each temperature.

## Fallback

No key, no network or a vendor error: replay the committed recording. It needs no key and opens no
socket. There is nothing to replay until `recorded/sampling.json` has been recorded (see the status
note above).

```sh
cd "$(git rev-parse --show-toplevel)/sessions/01-fundamentals/cursus/demos/model"
uv run --no-project --offline python sampling.py --replay
```

## Recorded runs

| Recording | Model | Run date | Attempt |
| --- | --- | --- | --- |
| `recorded/sampling.json` | not recorded yet (needs an API key, see Before class) | — | — |

## Reset

One command, from anywhere in the repository. It restores this folder to the committed state and
deletes `work/` and anything else an agent left here. Commit your own edits first.

```sh
git -C "$(git rev-parse --show-toplevel)" restore --source=HEAD --staged --worktree -- sessions/01-fundamentals/cursus/demos/model && git -C "$(git rev-parse --show-toplevel)" clean -fdx -- sessions/01-fundamentals/cursus/demos/model
```
