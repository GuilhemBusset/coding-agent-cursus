---
name: implement
description: Implement a GitHub epic or issue end to end with the implement loop (design, acceptance checks, implementation, cross-vendor review, evidence-gated merges). Invoke explicitly with /implement <issue> (Claude Code) or $implement <issue> (Codex). Do not invoke implicitly.
compatibility: Requires git, Python 3.11+, an authenticated GitHub CLI (gh), and both the Claude Code and Codex CLIs
disable-model-invocation: true
allowed-tools: Bash, Read
---

# implement — run the implement loop on an epic or an issue

You are the **operator** of a run: you start it, watch it, and talk to the user. You do not do the
work yourself. A deterministic engine (`tools/implementation-loop/`, started by
`scripts/implement.sh`) designs, checks, implements, reviews and merges every open sub-issue in
dependency order, using fresh headless Claude Code and Codex agents. The vendor that did not
write a change reviews it. See `docs/adr/0008-implement-loop.md`.

This skill body is checked in byte-identically at `.agents/skills/implement/SKILL.md` (Codex)
and `.claude/skills/implement/SKILL.md` (Claude Code); CI enforces the match. Implicit invocation
is disabled in both harnesses.

The argument is an issue number: an epic (all its open sub-issues) or a single issue (plus its
open prerequisites). Your operator name is `claude` if you are Claude Code, `codex` if you are Codex.

## 1. Preflight

Run `scripts/implement.sh doctor`. If anything is FAIL, stop and tell the user what to fix.
WARN lines are allowed but tell the user what they mean.

## 2. Plan

Run `scripts/implement.sh plan <issue>` and summarize it for the user: how many work items, how
many waves, what is already closed, any prerequisites pulled in from outside, every warning, and
the rough agent-call estimate. Point out issues that look too vague to prove (no checkboxes).

## 3. Confirm, explicitly

Tell the user plainly, then ask for a yes:
- The run merges each pull request into `main` **by itself** once every gate passes: the
  engine's own verification, a cross-vendor review with no reproduced defect, and the
  `required` CI check green on the exact reviewed commit.
- Issues close only when every checkbox has evidence; anything only a person can prove is left
  for them, never faked.
- There is no budget cap. Each call's cost is logged.

Proceed only on an explicit yes in this conversation. This yes is the merge approval the `ship`
skill would otherwise ask for, for every PR of this run.

## 4. Launch

Start the engine in the background and keep its log:

```sh
scripts/implement.sh run <issue> --operator <claude|codex> --yes
```

- Claude Code: run it with the Bash tool in the background.
- Codex: the engine needs network access (GitHub and both agent CLIs) and starts its own
  agents, so it cannot run inside your default sandbox. Run it with escalated permissions if
  your approval mode allows, or ask the user to run the exact command in a terminal.

A run for the same issue resumes where it stopped; `--fresh` starts over (only if the user asks).

## 5. Watch and report

Every few minutes, run `scripts/implement.sh status <issue>` and tell the user what changed:
issues merged and closed, issues waiting for a human and why, the cost so far. Do not poll in a
tight loop. Read `<run dir>/engine.log` (the path `status` prints) for detail.

When an issue stops in `needs_human`, explain the reason in plain words and what the user can
do: edit the issue to settle a disputed criterion, fix something by hand on its branch, or
leave it. Re-running the same command picks up edited issues.

## 6. Stop

`scripts/implement.sh stop <issue>` stops the run at its next safe point (running agents are
terminated; their issues resume later from the same phase).

## Hard rules

- Never edit files in the run's worktrees, never commit, push, merge, or tick issue checkboxes
  yourself. The engine does all of that, with evidence.
- Never pass `--yes` without the user's explicit confirmation in this conversation.
- Never use `--no-verify`, `--force`, or any way around the git hooks, the ruleset or CI.
