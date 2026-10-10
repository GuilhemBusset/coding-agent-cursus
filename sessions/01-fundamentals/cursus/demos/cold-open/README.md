# Cold open · a word problem to a certified LP

**Instructor runbook.** These are the first six minutes of Session 1, before any theory. Students
watch an agent read a short production-planning word problem, write a linear program, solve it on
HiGHS (open source, through `highspy`) and print a certificate: primal and dual objective, a
duality gap of 0, and the binding constraints. The point is not that the agent found an answer.
It is that the answer arrives with a proof anyone can check in one minute.

Like every demo, this runs on the instructor's Linux machine only (ADR 0010). Students do not run it.

| File | What it is |
| --- | --- |
| [`problem.md`](problem.md) | The word problem, shown to the room and read by the agent |
| [`prompt.txt`](prompt.txt) | The exact prompt both commands send, and nothing else |
| [`rehearsal.md`](rehearsal.md) | Two timed runs per CLI from a clean state, with versions and models |
| [`recorded/claude-run1.txt`](recorded/claude-run1.txt), [`recorded/claude-run2.txt`](recorded/claude-run2.txt) | Scrubbed Claude Code transcripts |
| [`recorded/codex-run1.txt`](recorded/codex-run1.txt), [`recorded/codex-run2.txt`](recorded/codex-run2.txt) | Scrubbed Codex transcripts |
| [`recorded/claude_run1_model.py`](recorded/claude_run1_model.py), [`recorded/claude_run2_model.py`](recorded/claude_run2_model.py) | The models Claude Code wrote, verbatim |
| [`recorded/codex_run1_model.py`](recorded/codex_run1_model.py), [`recorded/codex_run2_model.py`](recorded/codex_run2_model.py) | The models Codex wrote, verbatim |

The agent writes its model to `work/model.py` in this folder. `work/` is not tracked, and the reset
removes it.

## Before class (not timed)

1. Set up the session once, from the repo root: `bash setup/session-01-fundamentals.sh` (or
   `uv sync --locked` inside `sessions/01-fundamentals/`). This installs `highspy` into the
   session's `.venv/`. The demo needs it there, because the prompt forbids installing anything
   and the agent's sandbox may have no network.
2. Check the CLI you will use and that you are logged in: `claude --version` or
   `codex --version`, then any one-line prompt.
3. Run the [reset](#reset) and check that `git status --short --ignored --untracked-files=all -- .`
   prints nothing in this folder.
4. Put `problem.md` on the projector, and the terminal beside it, opened in this folder.

## Run

From this folder (`sessions/01-fundamentals/cursus/demos/cold-open/`), run one of the two
commands. These are the exact commands timed in [`rehearsal.md`](rehearsal.md). Run them as
written, so the live run matches the rehearsed one.

Claude Code:

```sh
claude -p "$(cat prompt.txt)" --permission-mode acceptEdits --allowedTools "Bash(uv run:*)" --output-format stream-json --verbose
```

Codex:

```sh
UV_CACHE_DIR="$PWD/work/.uv-cache" codex exec --sandbox workspace-write "$(cat prompt.txt)"
```

Why these flags:

- Both are headless, so nobody approves anything live. Claude Code may edit files
  (`acceptEdits`) and run only `uv run …` commands. Codex may write only in this folder
  (`workspace-write`), with no network.
- `--output-format stream-json --verbose` streams every tool call and tool result as it
  happens. Plain `-p` output would show only the final answer, and the room would miss the
  solve.
- `UV_CACHE_DIR` is there because Codex's sandbox cannot write to the default uv cache in your
  home folder. Without it, `uv run` fails with `Could not acquire lock … Read-only file system`.
  Pointing the cache at `work/.uv-cache` keeps it inside the writable folder. uv marks that
  folder as ignored by git, and the reset deletes it.

The interactive TUI (`claude` or `codex` started in this folder, then paste `prompt.txt`) also
works. It is easier to read on a projector, but it was **not** timed. You will have to approve
`uv run` when asked. Acceptance criterion A1 (under five minutes, twice in a row from a clean
state) covers only the two commands above.

## What to point at (six minutes)

| Time | On screen | Say |
| --- | --- | --- |
| 0:00 | `problem.md` | Read it aloud. Ask the room for a guess: all tables, all chairs, or a mix? Do not solve it. |
| 0:45 | Launch the command | "Same words you just read. Watch what it does, not what it says." |
| 1:00 | The agent writes `work/model.py` | Two variables, three hour constraints, a profit to maximise. Nothing about the answer is in the prompt. |
| 1:30 | The tool call `uv run python work/model.py` and its seven lines | This is the solver's output, not the model's prose. |
| 2:30 | `primal objective` = `dual objective`, `duality gap: 0` | The dual objective is an upper bound on every feasible plan's profit, and this plan reaches it. No search could do better, and you can check this without trusting the agent or the solver. |
| 3:30 | `binding constraints: assembly, carpentry` | Those two workstations are full. `finishing` has 10 hours left, so its dual is 0: one more finishing hour is worth nothing. |
| 4:30 | The duals | An extra assembly hour is worth 20 euros, an extra carpentry hour 10 euros. That is the dual objective, read as prices. |
| 5:30 | Close | "Today is about when to believe an agent. This is the easy case: it handed us a proof." |

What a correct run prints, give or take floating-point noise in the last digits:

```text
status: Optimal
solution: tables=20, chairs=20
duals: assembly=20, carpentry=10, finishing=0
primal objective: 1400
dual objective: 1400
duality gap: 0
binding constraints: assembly, carpentry
```

The optimum is unique: the profit ratio 40/30 lies strictly between the slopes of the two
binding constraints (1 and 2). The other corners of the feasible region earn less: 1200 for 30
tables and no chairs, 1350 for 15 tables and 25 chairs, 900 for 30 chairs and no tables.

## Known failure modes

- **The dual sign.** For a maximisation, some HiGHS versions and some formulations (for
  example a minimisation of the negated profit) report row duals that are negative. The
  prompt tells the agent to report non-negative shadow prices. If a run still prints
  `assembly=-20` and a dual objective of `-1400` with a gap of `2800`, do not hide it. It is a
  good live example of why we check certificates: the gap is not 0, so nothing is proven.
  The fix is one sign.
- **Noise in the last digits.** HiGHS may print `19.999999999999993` for 20. That is floating
  point, not a different answer, and the gap shows as something like `1e-12`.
- **A wall of solver log.** If the agent forgets `output_flag`, the HiGHS banner scrolls the
  certificate off screen. Scroll back to the seven lines.
- **A denied command (Claude Code).** Besides read-only commands, only `uv run …` is allowed. In
  both rehearsals the agent once chained `uv run python work/model.py; echo …; git …`, saw it
  denied, and re-ran the `uv run` part alone. This is harmless and costs a few seconds. Point
  out that the allow-list did its job.
- **A dual flipped with `abs()` (Codex).** One rehearsal forced the duals to be non-negative with
  `abs()`. That hides a wrong sign instead of fixing it, so say so if it shows up. The
  certificate still holds when the gap is 0 and the duals are dual-feasible, which anyone can
  check by hand.
- **`Reading additional input from stdin…` (Codex).** This appears when stdin is not a terminal,
  for example in a script. Run the command from an interactive shell.
- **No network, quota exhausted, or a login prompt.** Switch to the [fallback](#fallback) straight
  away rather than debugging in front of the room.

## Fallback

Use this for a dead network, an exhausted quota or a broken login. It needs no agent and no
network.

1. Open [`recorded/claude-run2.txt`](recorded/claude-run2.txt) (or
   [`recorded/codex-run2.txt`](recorded/codex-run2.txt) for a Codex room). Scroll through the
   `=== agent ===` section with the room: the prompt, the model being written, the tool call
   `uv run python work/model.py`, and its seven-line certificate.
2. Show the model the agent wrote,
   [`recorded/claude_run2_model.py`](recorded/claude_run2_model.py) (or
   [`recorded/codex_run2_model.py`](recorded/codex_run2_model.py)), then solve it live on local
   HiGHS from this folder:

   ```sh
   uv run --offline python recorded/claude_run2_model.py
   ```

   (or `uv run --offline python recorded/codex_run2_model.py`). It prints the same seven lines.
   `--offline` stops uv from touching the network. It works because the session's `.venv/` was
   synced before class, and the reset leaves it alone.
3. Then continue with "What to point at" from 2:30.

The run 1 files ([`claude-run1.txt`](recorded/claude-run1.txt),
[`claude_run1_model.py`](recorded/claude_run1_model.py),
[`codex-run1.txt`](recorded/codex-run1.txt),
[`codex_run1_model.py`](recorded/codex_run1_model.py)) are the first rehearsal of each pair. Two
independent runs that write different code and reach the same certificate are a point worth
making in Act II.

## Reset

One command. It works from any folder inside the repository. It puts this demo folder back to
the committed state: it removes `work/`, the uv cache under it, and any file an agent left
here, and it undoes edits to the tracked files.

```sh
git -C "$(git rev-parse --show-toplevel)" restore --source=HEAD --staged --worktree -- sessions/01-fundamentals/cursus/demos/cold-open && git -C "$(git rev-parse --show-toplevel)" clean -fdx -- sessions/01-fundamentals/cursus/demos/cold-open
```

**Warning:** it discards every uncommitted change in this demo folder, including your own edits to
this runbook, the prompt or the problem. Commit those first. It touches nothing outside the
folder: the session's `.venv/`, `setup/node_modules/` and the rest of the repository stay as they
are.
