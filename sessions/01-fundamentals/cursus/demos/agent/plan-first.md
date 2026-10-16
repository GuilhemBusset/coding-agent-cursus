# Plan first vs straight to code · runbook

"Plan first" is a habit worth having, but it is not free. Run the same task twice, same model,
same effort, each time on a fresh flipped-sense P00 export: once straight to code, once as a
read-only plan followed by a build of that plan. Put the bills side by side, then ask when the
plan pays for itself. On a one-line bug it does not, and that is the lesson: plan first when the
task is ambiguous or the change is wide, not by reflex.

The task is the [loop](loop.md)'s, with the same prompt (`LOOP_PROMPT` in `agent_demo.py`). One
`run plan` does both arms:

| Arm | Claude Code (`claude-opus-5-5`, medium) | Codex (`gpt-6-astra`, medium) |
| --- | --- | --- |
| 1, straight to code | the loop call: `--permission-mode acceptEdits --allowedTools "Bash(uv run pytest:*)"` | the loop call: `--sandbox workspace-write` |
| 2a, plan only (fresh export) | `--permission-mode plan`, prompt "Plan only. Do not edit … The task:" + the task | `--sandbox read-only`, the same prompt (`codex exec` has no plan mode) |
| 2b, build the plan (same export) | the loop call, prompt "Implement this plan: <plan> The task the plan was written for: <task>" | the same, `--sandbox workspace-write` |

Each call is a fresh headless session (`--no-session-persistence`, `--ephemeral`): the build sees
the plan only through its prompt. The script takes the plan from where this CLI version puts it
(Claude Code 2.1.301 in print mode: the result message, as no `ExitPlanMode` call was made;
Codex: its agent messages), records the source, stops if the plan is empty, and checks that the
plan call left the export unchanged before it builds.

## Before class

1. Do the shared setup in the [README](README.md#before-class) (warm uv cache, both CLIs logged in).
2. Rehearse once with the CLI you will show (commands under [Run](#run)), then run the [reset](#reset).
3. Keep the [Fallback](#fallback) replay commands ready in a second terminal.

## Timing

| Beat | Duration |
| --- | --- |
| Predict: which arm is cheaper, which is faster | 0:30 |
| Live `run plan` with one CLI (three calls, under a minute) | 1:30 |
| Read the plan it wrote, then the comparison table | 1:00 |
| Debrief: when a plan pays for itself | 1:00 |
| **Total** | **4:00** |

## Predict

"Same bug, same model. Planning first means one more call but maybe less flailing. Will the
planned arm use fewer tokens, or more? Fewer tool calls? Less time?"

## Run

From this folder (`sessions/01-fundamentals/cursus/demos/agent`):

```sh
uv run agent_demo.py reset plan             # fresh flipped-sense export, offline sync, pytest red
uv run agent_demo.py run plan --via claude  # direct arm, then plan and build, then the comparison
uv run agent_demo.py run plan --via codex   # the same with Codex
```

To make a new recording, add `--record --run 1` (then `--run 2`). Each arm starts with the same
reset as the reset command; the build runs in the plan's export, which the script has just
checked is unchanged.

## Expected outcome

Recorded on 2026-10-16. Every arm of every rehearsal ended green (the script's own pytest:
`30 passed`) with `p00_model.py` the only changed file, and every plan call changed nothing.
Tokens are each CLI's reported totals summed over the arm's calls (Claude Code: input, output,
cache read and cache write; Codex: input and output). Seconds are the arm's wall-clock time from
the recorded UTC start and end of each call.

| Recording | Arm | Tokens | Tool calls | Seconds | Files changed | Pytest exit code |
| --- | --- | --- | --- | --- | --- | --- |
| `plan-claude-run1` | direct | 60,547 | 5 | 10 | 1 | 0 |
| `plan-claude-run1` | planned | 219,382 | 11 | 33 | 1 | 0 |
| `plan-claude-run2` | direct | 81,058 | 5 | 17 | 1 | 0 |
| `plan-claude-run2` | planned | 192,316 | 9 | 35 | 1 | 0 |
| `plan-codex-run1` | direct | 66,507 | 5 | 17 | 1 | 0 |
| `plan-codex-run1` | planned | 121,787 | 6 | 30 | 1 | 0 |
| `plan-codex-run2` | direct | 66,670 | 6 | 15 | 1 | 0 |
| `plan-codex-run2` | planned | 122,616 | 9 | 27 | 1 | 0 |

What happened:

- **Both plans were right.** Each one named `p00_model.py:66`, `kMaximize` to `kMinimize`, and the
  objective contract, and none ran `uv run pytest` (both CLIs reasoned that it would write to
  the folder). So the plans are predictions from reading the code, and the build then reran
  everything: read, red, edit, green.
- **The planned arm cost more** in all four rehearsals: 1.8 to 3.6 times the tokens and 1.8 to
  3.3 times the seconds. The build started a fresh session and re-read what the plan had already read.
- **Claude Code's plan mode** read with shell commands (`ls`, `cat`, `grep`), which plan mode
  allows. In run 1 it also wrote its plan to `~/.claude/plans/…`, Claude Code's own plan file,
  outside the export. Both builds also tried `uv run python p00_model.py`, which the allow-list
  (`Bash(uv run pytest:*)`) refused; that is two of the extra tool calls.
- **Codex** has no plan mode in `codex exec`; the read-only sandbox and the "Plan only" prompt
  stand in for it, as in the lab-ladder rehearsal. In the TUI, `/plan` is the real thing.

Talking points: a plan is a checkpoint for *you*: it is where you catch a wrong diagnosis
before any edit. On a bug the tests already pin down, that checkpoint buys little. On a task
with no tests yet, or a wide change, the plan is what you review instead of a diff.

## Fallback

No login, no network, a CLI error or a refused model: replay the recordings. They start no CLI
and open no socket.

```sh
uv run agent_demo.py replay plan --via claude
uv run agent_demo.py replay plan --via codex
uv run agent_demo.py replay plan --via claude --run 2
uv run agent_demo.py replay plan --via codex --run 2
```

Each prints the three calls in order (tool calls with RED and GREEN pytest lines, the plan
itself, the build's final message), the plan's source, the token table per call and the
comparison.

## Recorded runs

Made with `uv run agent_demo.py run plan --via <cli> --record --run <N>`, one after the other,
never edited by hand. Times are UTC and cover all three calls. "Model source": `reported` means
the model is named in the CLI's own stream; `requested` means it is the `-m` value
(`codex exec --json` names no model).

| Recording | CLI | Version | Model | Model source | Effort | Date | Start | End | Plan source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [`plan-claude-run1`](recorded/plan-claude-run1.meta.json) | Claude Code | 2.1.301 | `claude-opus-5-5` | reported | medium | 2026-10-16 | 19:39:58 | 19:40:43 | result message |
| [`plan-claude-run2`](recorded/plan-claude-run2.meta.json) | Claude Code | 2.1.301 | `claude-opus-5-5` | reported | medium | 2026-10-16 | 19:40:43 | 19:41:36 | result message |
| [`plan-codex-run1`](recorded/plan-codex-run1.meta.json) | Codex | 0.162.1 | `gpt-6-astra` | requested | medium | 2026-10-16 | 19:41:37 | 19:42:24 | agent_message items (joined) |
| [`plan-codex-run2`](recorded/plan-codex-run2.meta.json) | Codex | 0.162.1 | `gpt-6-astra` | requested | medium | 2026-10-16 | 19:42:25 | 19:43:09 | agent_message items (joined) |

Per run, `-direct.jsonl`, `-plan.jsonl` and `-build.jsonl` are the raw streams of the three calls;
the meta holds each call's prompt and its sha256, the plan text, and the full state of the export
before and after each call.

## Reset

From this folder. It deletes only `<tempdir>/cursus-s1-agent/plan/`, exports a fresh
`flipped-sense` P00 there, syncs it offline and prints its pytest result (`1 failed, 29 passed`).

```sh
uv run agent_demo.py reset plan
```
