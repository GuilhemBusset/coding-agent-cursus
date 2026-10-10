# Cold open · rehearsal with both CLIs

**Instructor material.** This file records two consecutive runs of [the cold open](README.md) with
Claude Code and two with Codex, made on 2026-10-10 for issue #25. It is the evidence for "runs end
to end in under five minutes, twice in a row from a clean state" and for "CLI versions and models
recorded". Each run's full, scrubbed transcript and the model the agent wrote are in `recorded/`:

- Claude Code: [`claude-run1.txt`](recorded/claude-run1.txt) and
  [`claude_run1_model.py`](recorded/claude_run1_model.py),
  [`claude-run2.txt`](recorded/claude-run2.txt) and
  [`claude_run2_model.py`](recorded/claude_run2_model.py).
- Codex: [`codex-run1.txt`](recorded/codex-run1.txt) and
  [`codex_run1_model.py`](recorded/codex_run1_model.py),
  [`codex-run2.txt`](recorded/codex-run2.txt) and
  [`codex_run2_model.py`](recorded/codex_run2_model.py).

## Timings

Measured, not estimated. A run starts just before the runbook command is launched and ends after the
operator's re-run of `uv run python work/model.py` (the harness check) has printed its certificate.
Before each run, the README's reset ran and `git status --short --ignored --untracked-files=all -- .`
printed nothing in the demo folder. "Exit 0" means the agent command and the harness check both
exited 0.

| CLI | Run | Version | Model | Date | Start (UTC) | End (UTC) | Minutes | Exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Code | 1 | 2.1.296 | claude-opus-5-5 | 2026-10-10 | 2026-10-10T12:41:27Z | 2026-10-10T12:42:22Z | 0.92 | 0 |
| Claude Code | 2 | 2.1.296 | claude-opus-5-5 | 2026-10-10 | 2026-10-10T12:42:22Z | 2026-10-10T12:43:19Z | 0.95 | 0 |
| Codex | 1 | 0.160.0 | gpt-6-astra | 2026-10-10 | 2026-10-10T12:43:19Z | 2026-10-10T12:44:15Z | 0.93 | 0 |
| Codex | 2 | 0.160.0 | gpt-6-astra | 2026-10-10 | 2026-10-10T12:44:15Z | 2026-10-10T12:45:01Z | 0.77 | 0 |

Codex ran with reasoning effort `xhigh`, the default configuration of the instructor's account (see
the header in each Codex transcript).

Every run printed the same certificate in the agent's own tool call and again in the harness check:
`status: Optimal`, tables=20, chairs=20, duals assembly=20, carpentry=10, finishing=0, primal and
dual objective 1400, a duality gap of about 2.3e-13 (floating-point noise), and binding constraints
assembly and carpentry.

## What these numbers do and do not show

- **Agent time, not room time.** About one minute per run leaves roughly four minutes of the
  six-minute slot for reading the problem aloud, the guess and the explanation. A slow model day
  or a congested network can still eat that margin. Switch to the fallback rather than wait.
- **The headless commands only.** Each run used the README's Run command for that CLI,
  character for character, with `2>&1 | tee <log>` appended to capture it. The interactive TUI was
  not timed.
- **Two runs, two different programs.** In both Claude Code runs the agent first wrote a sign flip
  for the duals, then checked HiGHS's raw row duals (already non-negative for this maximisation in
  highspy 1.15.1), removed the flip and only then ran the model. Both Codex runs instead forced
  every dual to be non-negative: a conditional flip in run 1, `abs()` in run 2. This is the
  dual-sign trap listed in the runbook, met for real. `abs()` is worth a remark in Act II: it would
  hide a wrong sign rather than fix it. The certificate still holds here, because dual feasibility
  and the zero gap can be checked by hand.
- **Scope.** All four agents read only `problem.md` and wrote only `work/model.py`. In each Claude
  Code run, a compound command (`uv run python work/model.py; echo "exit=$?"; git …`) was denied
  by the `Bash(uv run:*)` allow-list. The agent re-ran `uv run python work/model.py` on its own and
  carried on. This cost a few seconds and is visible in the transcripts.
- **One machine**: Linux (WSL2), both CLIs logged in with the instructor's accounts.

## Setup used

- Source: a throwaway `git clone` of the base commit `dadb0e1` (branch `feat/s1-demo-cold-open`)
  into a temporary folder outside the loop's worktree. The demo's `README.md`, `problem.md` and
  `prompt.txt` (the shipped files, see the sha256 values in each transcript's meta) were copied in
  and committed locally as `0be4cf5` in that clone only. The clone was never pushed and was deleted
  afterwards. `rehearsal.md` and `recorded/` did not exist yet. In class they sit beside the prompt,
  which tells the agent to read only `problem.md`.
- `uv sync --locked` ran once in the clone's `sessions/01-fundamentals/` before the first run. It
  was not timed, as in the runbook's "Before class".
- A driver script ran, for each CLI and run, from the clone's demo folder: the README reset line
  (verbatim), the clean-state `git status`, `date -u +%FT%TZ`, the runbook command, the harness
  `uv run python work/model.py`, `date -u +%FT%TZ`, then copied `work/model.py` into `recorded/`
  verbatim. The script ran the command with stdin from `/dev/null` and the terminal copy discarded
  (`tee` kept the log), which is why Codex prints `Reading additional input from stdin...`.

## Redactions in the transcripts

- Claude Code's `stream-json` output is condensed to readable lines: the init line (model,
  permission mode, CLI version, working folder), tool calls, tool results, assistant text and the
  final result. Thinking blocks and system events other than init are dropped, and
  `rate_limit_event` lines are shown by name only. Nothing is clipped. The model file the agent
  wrote is shown in full under `[tool call content]`.
- Codex output is kept as printed, except one line. Codex echoes the user prompt in its header,
  and that echo is replaced by `[user prompt elided: the contents of prompt.txt, sha256 …]`, because
  it is the shipped `prompt.txt`, unchanged (same sha256).
- Then both were scrubbed: the temporary rehearsal folder is shown as `<rehearsal>`, the home
  directory as `~` and the local user name as `<user>`. Session IDs and other UUIDs are shown as
  `<session-id>`, e-mail addresses as `<email>` and token-like strings as `<token>`.
- The answer is not redacted. It is public and it is the point of the demo.
