# Act II · the effort dial, one problem at low and high effort

**Instructor runbook.** Six minutes in Act II. The room bets on what turning the effort dial up buys,
then watches one small operations-research puzzle (a knapsack) solved at `low` and at `high`
effort. A script counts the tokens, the wall time, the list-price cost, and checks the answer
against a brute-force oracle. The lesson is the trade: more thinking costs tokens, seconds and
money, and on a problem the model already gets right it buys nothing else.

Like every demo, this runs on the instructor's Linux machine only (ADR 0010). Students do not run it.

| File | What it is |
| --- | --- |
| [`prompt.txt`](prompt.txt) | The exact puzzle sent to every run, on stdin |
| [`effort.py`](effort.py) | The script: the parcel table, the brute-force oracle, `live`, `replay` and `prompt` |
| [`prices.json`](prices.json) | List prices in USD per million tokens, with their as-of date and source pages |
| [`recorded/results.json`](recorded/results.json) | The recorded runs: one row per CLI and effort, plus the prices used |
| `recorded/raw/<cli>-<effort>.jsonl` | Each CLI's raw JSON event stream, scrubbed (see [Recording](#recording)) |
| `recorded/raw/<cli>-<effort>.meta.json` | Each run's command line, prompt sha256, CLI version, UTC start and end, wall time, exit code |

`effort.py` renders `prompt.txt` from its parcel table (`uv run effort.py prompt` prints it), and
`live` refuses to run if the two differ. A live run writes only to `work/` in this folder, and the
reset removes it.

## The puzzle

A van with a 63 kg limit and eight parcels (weight, value): A (28, 67), B (9, 52), C (6, 20),
D (10, 64), E (27, 68), F (27, 29), G (16, 45), H (30, 61). The best load is B, D, E, G: 62 kg,
229 EUR. Two traps sit next to it. Filling the van to exactly 63 kg (A, B, D, G) gives 228, one
short. Loading by value per kilo (greedy) gives 181. The oracle checks all 256 subsets; the
script scores a run as correct only when its last `ANSWER:` line is the integer 229.

## Before class (not timed)

1. Set up the session once, from the repo root: `bash setup/session-01-fundamentals.sh` (or
   `uv sync --locked` inside `sessions/01-fundamentals/`). The script uses only the standard
   library, but `uv run` needs the session's `.venv/`.
2. Check the CLI you will use and that you are logged in: `claude --version` or `codex --version`,
   then any one-line prompt. The recording used Claude Code 2.1.296 and codex-cli 0.162.1.
3. Check the fallback works offline: `uv run --offline effort.py replay` must print the table under
   [Expected outcome](#expected-outcome).
4. Run the [reset](#reset). Open a terminal in this folder (`sessions/01-fundamentals/cursus/demos/effort/`)
   and put `prompt.txt` on the projector beside it.

## Run

From this folder, run the command for the CLI you have. Each one runs the same prompt twice,
`low` then `high`, and prints the table at the end. Progress lines go to stderr.

Claude Code (the effort setting is `--effort`, model `claude-opus-5-5`):

```sh
uv run effort.py live --cli claude
```

Codex (the effort setting is `-c model_reasoning_effort="low"` or `"high"`, model `gpt-6-astra`):

```sh
uv run effort.py live --cli codex
```

With both CLIs installed, `uv run effort.py live --cli both` runs all four. `--claude-model ID` and
`--codex-model ID` override the models; add the model's rates to `prices.json` first, or the run
stops with "No price for model".

What each run does, so nobody wonders whether the agent "cheated":

- It runs in a fresh, empty temporary folder outside the repository, deleted afterwards. The
  model never sees the oracle, the recording or the repo's `AGENTS.md`.
- Claude Code: `claude -p --output-format stream-json --verbose --effort <low|high> --model
  claude-opus-5-5 --no-session-persistence --strict-mcp-config --tools "" --permission-mode dontAsk`,
  with the prompt on stdin. `--tools ""` removes every tool.
- Codex: `codex exec --json --ephemeral --skip-git-repo-check -C <tmp> --sandbox read-only
  -c approval_policy="never" -c model_reasoning_effort="<low|high>" -m gpt-6-astra -`, with the
  prompt on stdin. This command does not remove Codex's shell tool, so the prompt forbids tools,
  the sandbox is read-only, and the script counts tool calls anyway.
- Any run that called a tool, or where Claude Code still offered tools, is marked `(used tools)`
  in the table and `pure_reasoning: false` in `results.json`.

The settings are documented here (checked 2026-10-11):

- Claude effort parameter: https://platform.claude.com/docs/en/build-with-claude/effort. The levels
  are `low`, `medium`, `high`, `xhigh` and `max`. Opus 5.5 defaults to `medium`.
- Codex `model_reasoning_effort`: https://developers.openai.com/codex/config-reference. The levels
  available depend on the model. Always pass it explicitly. The instructor account's default was
  `xhigh` in the cold-open rehearsal.

## Timing (six minutes)

| Time | On screen | Say |
| --- | --- | --- |
| 0:00 | `prompt.txt` | Read the puzzle. Ask the [predict question](#predict) and have everyone write down three multipliers and a yes or no. |
| 1:00 | Launch `uv run effort.py live --cli claude` (or `codex`) | "Same prompt, same model, twice. Only the effort setting changes. No tools, empty folder." |
| 1:30 | Progress lines on stderr | The low run ends in about 10 s (Claude Code) or 20 s (Codex). The high run takes a little longer. |
| 2:30 | The table | Read one row aloud: output tokens, reasoning tokens, seconds, dollars, answer, correct. |
| 3:15 | The "High effort divided by low effort" lines | Compare them with the room's bets. If people bet 5× or 10×, that gap is the discussion. |
| 4:15 | `input tok` and `cache write` columns | The same at both efforts: that is the agent's own system prompt, paid on every call. On a small puzzle it is about half the bill. |
| 5:15 | Close | "The dial is an allowance, not a guarantee. Turn it up when the problem is hard and checkable, not by default." |

If the high run is still going after about two minutes, press Ctrl-C and switch to the
[fallback](#fallback). Do not wait in front of the room.

## Predict

Ask it before launching, and have people commit to numbers:

> At high effort, roughly how many times more output tokens, seconds and dollars will it spend,
> and will it get right what low effort gets wrong?

Offer a scale to bet on (1×, 2×, 5×, 10×) for each of the three. The question is a bet on one run,
not on an average.

## Expected outcome

The recorded run of 2026-10-11, exactly as `uv run --offline effort.py replay` prints it:

```text
Effort dial - knapsack, capacity 63 kg - optimum by brute force over all subsets: 229
Run date 2026-10-11 (UTC) - prices as of 2026-10-11, USD list-price equivalent

CLI     effort  model            input tok  output tok  cache read  cache write  reasoning  seconds  cost USD  answer  correct
------  ------  ---------------  ---------  ----------  ----------  -----------  ---------  -------  --------  ------  -------
claude  low     claude-opus-5-5          2         783           0        2,666        286      9.9    0.0370     229  yes
claude  high    claude-opus-5-5          2         964           0        2,666        447     11.2    0.0406     229  yes
codex   low     gpt-6-astra         14,348         467      12,288            -        286     18.6    0.0562     229  yes
codex   high    gpt-6-astra         14,348         705      12,288            -        516     30.5    0.0681     229  yes

Claude counts input without cache reads/writes; Codex counts cached tokens inside input.
reasoning = Claude thinking tokens or Codex reasoning tokens, already counted in output.
High effort divided by low effort, per CLI:
  claude  output tokens x1.2   reasoning x1.6   seconds x1.1   cost x1.1
  codex   output tokens x1.5   reasoning x1.8   seconds x1.6   cost x1.2
```

What to draw from it:

- **Both efforts were correct, in both CLIs.** Here high effort bought no correctness. It bought
  about 1.6 to 1.8 times the reasoning tokens, 1.1 to 1.6 times the time and 1.1 to 1.2 times
  the cost. The lesson for this puzzle is cost and time, not accuracy.
- **The fixed cost dominates.** The input side (Claude Code's 2,666-token system prompt written to
  the 1-hour cache, Codex's 14,348 input tokens) is identical at both efforts and is 48 to 59
  percent of each bill. The effort dial only moves the output side.
- **If a live run differs,** that is the demo working, not failing. A low run that answers 228
  (the full van) or 181 (greedy) while high gets 229 is the case where thinking bought
  correctness. A high run that is slower and still wrong is the overthinking case from the
  deck. Either way, **one sample is an anecdote, not a rate**. Two runs at the same effort can
  differ, as the cold open showed. Claims about effort need many samples and a verifier, which is
  exactly what the test-time-compute lab simulates.

How the cost is computed (USD list-price equivalent: a subscription login is not billed per token):

- Claude Code reports exclusive counters per model in `modelUsage`: input excludes cache reads and
  writes, output includes thinking. Cost = input × input rate + cache write × write rate for its
  duration + cache read × read rate + output × output rate, summed over every model in
  `modelUsage`. `modelUsage` does not say how long a write is cached, so the script reads the
  result's `usage.cache_creation` split (`ephemeral_1h_input_tokens`, `ephemeral_5m_input_tokens`)
  and prices 1-hour writes at the 1-hour rate ($8 per million for Opus 5.5) and 5-minute writes at
  the 5-minute rate ($5). Both recorded Claude runs wrote their 2,666-token system prompt to the
  1-hour cache, kept as `cache_write_1h` next to `cache_write` in `results.json`. Without a
  reported split, every write is priced at the 5-minute rate.
- Codex reports inclusive counters per turn: `input_tokens` includes `cached_input_tokens` and
  `cache_write_input_tokens`, and `output_tokens` includes `reasoning_output_tokens`. Cost =
  (input − cached − cache write) × input rate + cached × cached-input rate + cache write ×
  cache-write rate + output × output rate. The script refuses usage where cached plus cache-write
  tokens exceed input or reasoning exceeds output, and a nonzero cache write for a model with no
  `cache_write` rate in `prices.json`. Both recorded runs report `cache_write_input_tokens` of 0.
- Claude Code also reports its own `total_cost_usd`, kept as `reported_cost_usd`. In both Claude
  runs it equals the script's cost exactly: low (2 × $4 + 2,666 × $8 + 783 × $20)
  per million = $0.036996, high (2 × $4 + 2,666 × $8 + 964 × $20) per million = $0.040616, so
  `cost_delta_usd` = `cost_usd` − `reported_cost_usd` = 0.

## Known failure modes

- **A formatted answer.** If a model writes `ANSWER: **229**` or `ANSWER: 229 EUR`, the script
  finds no integer and scores the run as incorrect. Say so and show the raw line in
  `work/raw/<cli>-<effort>.jsonl`. The prompt asks for a plain integer, and the script parses
  strictly rather than guessing.
- **A tool call.** If a Codex run executes a command despite the prompt, its row says
  `(used tools)`. It is no longer pure reasoning: point that out instead of hiding it.
- **Your own Claude Code hooks and plugins.** `--tools ""` removes tools, but your user-level
  `SessionStart` hooks still run (the recording shows one, with empty output). They do not change
  the counts unless they print context into the session.
- **A different effort level name.** If a CLI rejects `low` or `high` for a model, the run exits
  nonzero and the script stops with the CLI's error. Check the docs links above.
- **No network, quota exhausted, or a login prompt.** Switch to the [fallback](#fallback) straight
  away rather than debugging in front of the room.

## Fallback

Use this for a dead network, an exhausted quota or a broken login. It needs no CLI and no network:

```sh
uv run --offline effort.py replay
```

It prints the recorded table above. `--offline` stops uv from touching the network; it works
because the session's `.venv/` was synced before class. Then continue the timing from 2:30. To show
the evidence, open `recorded/raw/claude-high.jsonl` (or `codex-high.jsonl`) and find the final
`ANSWER: 229` and the usage counters.

After a live run, `uv run effort.py replay --dir work` prints that run's table again.

## Recording

Four live runs, one per CLI and effort, made on **2026-10-11** on the instructor's Linux machine
(WSL2) with `uv run effort.py live --cli both`, both CLIs logged in with the instructor's accounts.
The run date is the UTC date of the first run's start. Prices were read from the vendor pages the
same day (as of 2026-10-11).

| CLI | Version | Model | Effort | Start (UTC) | End (UTC) | Seconds | Exit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Code | 2.1.296 | claude-opus-5-5 | low | 2026-10-11T12:28:30.107Z | 2026-10-11T12:28:40.010Z | 9.903 | 0 |
| Claude Code | 2.1.296 | claude-opus-5-5 | high | 2026-10-11T12:28:40.011Z | 2026-10-11T12:28:51.165Z | 11.155 | 0 |
| Codex | 0.162.1 | gpt-6-astra | low | 2026-10-11T12:28:51.173Z | 2026-10-11T12:29:09.793Z | 18.62 | 0 |
| Codex | 0.162.1 | gpt-6-astra | high | 2026-10-11T12:29:09.794Z | 2026-10-11T12:29:40.308Z | 30.514 | 0 |

Prices used, standard list prices in USD per million tokens (MTok), as of 2026-10-11:

| Model | Input | Output | Cache write (Claude: 5 min) | Cache write, 1 h | Cache read / cached input |
| --- | --- | --- | --- | --- | --- |
| claude-opus-5-5 | $4 | $20 | $5 | $8 | $0.20 |
| gpt-6-astra | $10 | $50 | $12.50 | n/a | $1 |

Sources: Anthropic, https://platform.claude.com/docs/en/about-claude/pricing (Opus 5.5 row of the
model pricing table); OpenAI, https://platform.openai.com/docs/pricing (gpt-6-astra, standard tier,
short context; Codex reported no cache writes in these runs, so their $12.50 rate did not apply).
`prices.json` also holds the Sonnet 5.5 and Haiku 5.5 rates, for runs where Claude Code calls
an auxiliary model. The recorded runs used only `claude-opus-5-5`.

Notes on the recording:

- A first full run a few minutes earlier, made before the reasoning column was added to the table,
  also gave 229 in all four cases with similar counts. It was replaced by this run, not kept.
- The raw files are the CLIs' stdout, scrubbed: the temporary folder is shown as `<tmp>`, the home
  folder as `~` and the user name as `<user>`. Session IDs and other UUIDs became `<session-id>`,
  message and request IDs `<message-id>` and `<request-id>`, and the local socket path
  `<socket>`. No e-mail address appeared. No token, timing, model or answer field was changed,
  and `results.json` re-derives from the raw files.
- `prompt_sha256` in every meta file is the sha256 of the shipped `prompt.txt`
  (`f5e2a7ab6c6f8c175bae05f6397fdce7ce6766794d58c2448fd064e4f6922163`).

## Reset

One command. It works from any folder inside the repository. It puts this demo folder back to the
committed state: it removes `work/` and anything else a run left here, and it undoes edits to the
tracked files.

```sh
git -C "$(git rev-parse --show-toplevel)" restore --source=HEAD --staged --worktree -- sessions/01-fundamentals/cursus/demos/effort && git -C "$(git rev-parse --show-toplevel)" clean -fdx -- sessions/01-fundamentals/cursus/demos/effort
```

**Warning:** it discards every uncommitted change in this demo folder, including your own edits to
this runbook, the prompt, the prices or the recording, and any live results in `work/`. Commit or
copy those first. It touches nothing outside the folder: the session's `.venv/`,
`setup/node_modules/` and the rest of the repository stay as they are.
