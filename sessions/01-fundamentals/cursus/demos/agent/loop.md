# The agent loop on P00 · runbook

The model is a pure function of its context; the agent is that model in a loop the harness
runs: read, act, observe, repeat. Show one task go round the loop, red to green, and then show
the same task, the same prompt and the same loop in the other harness. The point is the harness,
not the brand.

The task is the `flipped-sense` P00 export: the model maximizes cost instead of minimizing it,
HiGHS still says "optimal" (1085), and only the objective contract (`KNOWN_OPTIMUM = 485`)
catches it. The prompt is fixed in `agent_demo.py` (`LOOP_PROMPT`), identical for both CLIs:
read `README.md` and `p00_model.py`, run `uv run pytest`, fix only `p00_model.py` (no test,
checker or data edits, no hard-coding), run `uv run pytest` again, and name the broken contract.

| Harness | Call (cwd: the export) |
| --- | --- |
| Claude Code | `claude -p <prompt> --model claude-opus-5-5 --effort medium --permission-mode acceptEdits --allowedTools "Bash(uv run pytest:*)" --strict-mcp-config --no-session-persistence --output-format stream-json --verbose` |
| Codex | `codex exec --json --ephemeral -C <export> --sandbox workspace-write -c approval_policy="never" -m gpt-6-astra -c model_reasoning_effort="medium" <prompt>` |

After the agent stops, the script runs the export's contract suite itself and prints its own
verdict and the changed files; the agent's word is not the evidence.

## Before class

1. Do the shared setup in the [README](README.md#before-class) (warm uv cache, both CLIs logged in).
2. Rehearse once with each CLI (commands under [Run](#run)), then run the [reset](#reset).
3. Keep the [Fallback](#fallback) replay commands ready in a second terminal.

## Timing

| Beat | Duration |
| --- | --- |
| Show the export: `uv run pytest` is red, HiGHS says optimal | 0:45 |
| Predict | 0:30 |
| Live loop in Claude Code | 0:45 |
| Same loop in Codex | 0:45 |
| Debrief: the loop, the evidence, the swap | 1:15 |
| **Total** | **4:00** |

Each recorded loop took 13 to 15 seconds of agent time.

## Predict

"The tests are red and the solver says optimal. How many tool calls before the agent has a
green run, and will the two harnesses take the same path?" Take two or three guesses.

## Run

From this folder (`sessions/01-fundamentals/cursus/demos/agent`):

```sh
uv run agent_demo.py reset loop            # fresh flipped-sense export, offline sync, pytest red
uv run agent_demo.py run loop --via claude # reset again, then the loop in Claude Code
uv run agent_demo.py run loop --via codex  # reset again, then the same loop in Codex
```

To make a new recording, add `--record --run 1` (then `--run 2` after it). `run` always starts
with the reset, so two runs in a row each start from the same clean state.

The script prints each native tool call as it happens (`tool  Read …`, `tool  exec …`,
`tool  edit …`), the pytest summary of each test run marked RED or GREEN, the agent's last
message, then its own pytest result, the changed files and the token table.

## Expected outcome

Recorded on 2026-10-16, all four rehearsals took the same path:

- **Claude Code** (`claude-opus-5-5`, medium): Read `README.md`, Read `p00_model.py`,
  `uv run pytest` → RED `1 failed, 29 passed` (`test_objective_contract`), Edit `p00_model.py`,
  `uv run pytest` → GREEN `30 passed`. Five tool calls, about 81k tokens (almost all cache reads).
- **Codex** (`gpt-6-astra`, medium): `cat README.md`, `cat p00_model.py`, `uv run pytest` → RED,
  an `apply_patch` edit of `p00_model.py`, `uv run pytest` → GREEN, then `rg -n
  "changeObjectiveSense" p00_model.py` to cite the line. Six tool calls, about 50k tokens.

Both name the objective contract and `p00_model.py:66` (`kMaximize` back to `kMinimize`). In every
run the script's own pytest after the agent reports `30 passed` and the only changed file is
`p00_model.py`; the tests, checker and data are byte-identical to the export.

Talking points:

- Same prompt, same loop (read, run, observe, edit, run), different harness. What differs is the
  harness's tools (`Read`/`Edit` vs shell and `apply_patch`) and its bookkeeping (Claude Code
  reports cache reads and writes separately, Codex reports cached input).
- Green is not the proof: the next run of the contract suite is, and so is `git diff`. The script
  checks both; ask the room what a hard-coded "485" would have passed (see the lab notes in
  `exercises/p00-lab/README.md`).
- If a live run goes differently (another order, an extra look around, a refused command), say
  so: the loop is the same even when the path is not.

The narrative's "the agent forgets an earlier instruction" beat belongs to the
[context bomb](context-bomb.md) and is talk track, not a scripted outcome.

## Fallback

No login, no network, a CLI error or a refused model: the script stops with a message that ends
with the replay command. Replay the recordings instead. They start no CLI and open no socket.

```sh
uv run agent_demo.py replay loop --via claude
uv run agent_demo.py replay loop --via codex
uv run agent_demo.py replay loop --via claude --run 2
uv run agent_demo.py replay loop --via codex --run 2
```

Each prints the recorded tool calls with their RED and GREEN pytest lines, the agent's final
message, the script's own before and after pytest results and the token table.

## Recorded runs

Made with `uv run agent_demo.py run loop --via <cli> --record --run <N>`, one after the other with
the reset between, never edited by hand. Times are UTC. "Model source" says whether the model is
the one the CLI reported in its stream (`reported`) or the one requested on the command line
(`requested`; `codex exec --json` names no model).

| Recording | CLI | Version | Model | Model source | Effort | Date | Start | End | Tool calls | Tokens | Final pytest | Changed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [`loop-claude-run1`](recorded/loop-claude-run1.meta.json) | Claude Code | 2.1.301 | `claude-opus-5-5` | reported | medium | 2026-10-16 | 19:38:07 | 19:38:20 | 5 | 80,956 | 30 passed | p00_model.py |
| [`loop-claude-run2`](recorded/loop-claude-run2.meta.json) | Claude Code | 2.1.301 | `claude-opus-5-5` | reported | medium | 2026-10-16 | 19:38:44 | 19:38:58 | 5 | 80,991 | 30 passed | p00_model.py |
| [`loop-codex-run1`](recorded/loop-codex-run1.meta.json) | Codex | 0.162.1 | `gpt-6-astra` | requested | medium | 2026-10-16 | 19:38:59 | 19:39:14 | 6 | 49,808 | 30 passed | p00_model.py |
| [`loop-codex-run2`](recorded/loop-codex-run2.meta.json) | Codex | 0.162.1 | `gpt-6-astra` | requested | medium | 2026-10-16 | 19:39:14 | 19:39:29 | 6 | 49,823 | 30 passed | p00_model.py |

Raw streams: [`loop-claude-run1.jsonl`](recorded/loop-claude-run1.jsonl),
[`loop-claude-run2.jsonl`](recorded/loop-claude-run2.jsonl),
[`loop-codex-run1.jsonl`](recorded/loop-codex-run1.jsonl),
[`loop-codex-run2.jsonl`](recorded/loop-codex-run2.jsonl). Tokens are the CLI's own counters
(Claude Code: input, output, cache read and cache write; Codex: input and output).

## Reset

From this folder. It deletes only `<tempdir>/cursus-s1-agent/loop/`, exports a fresh
`flipped-sense` P00 there, syncs it offline and prints its pytest result (`1 failed, 29 passed`).
Nothing in the course checkout changes.

```sh
uv run agent_demo.py reset loop
```
