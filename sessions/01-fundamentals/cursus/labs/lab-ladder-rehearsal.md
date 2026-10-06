# Lab ladder · rehearsal with both CLIs

**Instructor material.** This file records one rehearsal of [the lab ladder](../../exercises/lab-ladder.html)
L1 to L3 with Claude Code and one with Codex, run on 2026-10-06 for issue #43. It is the evidence for the
acceptance criterion "an agent session completes L1 to L3 with each CLI inside the time boxes, and the
timings are recorded". The full, scrubbed transcripts are in
[`lab-ladder-evidence/claude.txt`](lab-ladder-evidence/claude.txt) and
[`lab-ladder-evidence/codex.txt`](lab-ladder-evidence/codex.txt).

## Timings

Measured, not estimated. Each level starts when its first command starts (the export for L1 and L2, the
plan turn for L3) and ends when its done commands have passed. The boxes come from the page's
`data-box` attributes.

| CLI | Level | Version | Model | Date | Start (UTC) | End (UTC) | Minutes | Box (min) | Done exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Code | L1 | 2.1.291 | claude-opus-5-5 | 2026-10-06 | 2026-10-06T18:11:28Z | 2026-10-06T18:12:54Z | 1.43 | 8 | 0 |
| Claude Code | L2 | 2.1.291 | claude-opus-5-5 | 2026-10-06 | 2026-10-06T18:12:54Z | 2026-10-06T18:13:21Z | 0.45 | 12 | 0 |
| Claude Code | L3 | 2.1.291 | claude-opus-5-5 | 2026-10-06 | 2026-10-06T18:13:21Z | 2026-10-06T18:15:27Z | 2.1 | 15 | 0 |
| Codex | L1 | 0.160.0 | gpt-6-astra (reasoning effort xhigh) | 2026-10-06 | 2026-10-06T18:11:29Z | 2026-10-06T18:12:24Z | 0.92 | 8 | 0 |
| Codex | L2 | 0.160.0 | gpt-6-astra (reasoning effort xhigh) | 2026-10-06 | 2026-10-06T18:12:24Z | 2026-10-06T18:13:05Z | 0.68 | 12 | 0 |
| Codex | L3 | 0.160.0 | gpt-6-astra (reasoning effort xhigh) | 2026-10-06 | 2026-10-06T18:13:05Z | 2026-10-06T18:14:50Z | 1.75 | 15 | 0 |

"Done exit 0" means every done command of the level passed with the output the page asks for: L1 printed
nothing for `git status --short` and `git diff --exit-code HEAD`, and `git grep -n changeObjectiveSense`
found the line both agents cited (`p00_model.py:66`); L2 printed nothing for `git diff --stat -- tests/`,
`uv run pytest` passed 30 tests, and `git status --short` listed only `M p00_model.py`; L3 printed `PASS`,
headcount 11, LP bound 10.2 and `Gap to the LP bound: 0.8 (7.27%)`, and `git status --short -- check.py data
wrong` printed nothing.

## What these numbers do and do not show

- **Agent time, not student time.** The rehearsal was scripted and headless: no reading, typing,
  predicting on paper or reviewing the plan by a person. The numbers show that each agent can do the work
  well inside its box; the remaining slack (at least 6 minutes per level) is for the student. L3 is still
  the level most likely to overrun in the room, because the plan review is human work.
- **Headless equivalents of the page's interactive steps.** An unattended run cannot drive a TUI, so each
  interactive step used the documented non-interactive form of the same mode:

  | Page step | Claude Code rehearsal | Codex rehearsal |
  | --- | --- | --- |
  | L1 read-only | `claude -p "<L1 prompt>" --permission-mode plan` | `codex exec --sandbox read-only "<L1 prompt>"` |
  | L2 fix, approving commands | `claude -p "<L2 prompt>" --permission-mode acceptEdits --allowedTools "Bash(uv run pytest:*)"` (the allow-list stands in for the student approving `uv run pytest`) | `codex exec --sandbox workspace-write "<L2 prompt>"` |
  | L3 plan mode | `claude -p "<plan prompt>" --permission-mode plan` | `codex exec --sandbox read-only "<plan prompt>"` (the design's fallback; `/plan` is TUI-only) |
  | L3 leave plan mode, build | `claude -p "<build prompt>" --resume <session> --permission-mode acceptEdits --allowedTools "Bash(uv run:*)"` | `codex exec resume <session> -c sandbox_mode="workspace-write" "<build prompt>"` |

  Every prompt was read from the page's prompt blocks at run time, so the rehearsal used the page's exact
  text. The plan turn changed no file in either rehearsal (`git status --short --untracked-files=all -- .`
  in the L3 folder printed nothing after it); the build turn resumed the same session.
- **Codex `/plan` is verified, but not rehearsed.** The page tells Codex users to type `/plan`. It is
  listed in the Codex slash-command docs (https://developers.openai.com/codex/cli/slash-commands, read
  2026-10-06), and the installed 0.160.0 binary contains the command ("switch to Plan mode") and its exit
  prompt ("Implement this plan?" / "Yes, implement this plan"). The TUI itself was not driven.
- **Codex and the uv cache.** In `workspace-write`, Codex found the default uv cache read-only and set
  `UV_CACHE_DIR` to a folder inside the workspace (L2) or under `/tmp` (L3) on its own. uv marks its cache
  folder as ignored by Git, so `git status --short` stayed clean. In the interactive lab, Codex asks for
  approval instead; the L2 instructor hint covers it.
- **One machine, one run each**: Linux (WSL2), both CLIs logged in with the instructor's accounts and their
  default configuration. Timings will vary with model load and with each student's account.

## Setup used

- Source: a throwaway `git clone -b feat/s1-lab-ladder` of the branch at `8b2937c` into a temporary folder
  outside the loop's worktree, with the implementation's uncommitted `exercises/p00-lab/export.py`
  (sha256 `002e3782d5351e43402d7cb92546b0719dbf387b1ba564c9c937573d12c87ce3`, the same file this
  change ships) and `exercises/lab-ladder.html` copied in. `uv sync --locked` ran before L1 and is
  not timed (setup is done before the lab).
- Exports, as on the page, from `sessions/01-fundamentals`: `--tests-dir --bug none` into `p00-explore`
  for L1, `--tests-dir --bug dropped-demand` into `p00-fix` for L2.
- L3 ran in the clone's `sessions/01-fundamentals/exercises/l3-word-problem`. Its `solution.json` and
  `work/` stayed in the throwaway clone and are not part of this repository.

## Redactions in the transcripts

Claude Code's `stream-json` output is condensed to the model line, assistant text, tool calls and tool
results (each clipped). Codex output is kept as printed. Both were then scrubbed:

- the temporary rehearsal folder is shown as `<rehearsal>`, the home directory as `~`, and the local user
  name as `<user>`;
- session IDs and every other UUID are shown as `<session-id>`; e-mail addresses as `<email>`; nothing
  token-like was found, but the scrubber would show it as `<token>`;
- the L3 answer key is removed: the content of the model files the agents wrote in `work/` and every copy
  of the final roster in `solution.json`, each replaced by a `[redacted: L3 answer key ...]` line. The
  repository is public, and the checker output (PASS, headcount, bound and gap) is kept.
