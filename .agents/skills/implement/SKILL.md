---
name: implement
description: Implement a GitHub epic or issue end to end with the implement loop (design, acceptance checks, implementation, cross-vendor review, evidence-gated merges), autonomously from launch to final report. Invoke explicitly with /implement <issue> (Claude Code) or $implement <issue> (Codex). Do not invoke implicitly.
compatibility: Requires git, Python 3.11+, an authenticated GitHub CLI (gh), and both the Claude Code and Codex CLIs
disable-model-invocation: true
allowed-tools: Bash, Read
---

# implement — run the implement loop on an epic or an issue

You are the **operator** of a run: you start it and you report its result. You do not do the
work, and you do not relay questions. A deterministic engine (`tools/implementation-loop/`,
started by `scripts/implement.sh`) designs, checks, implements, reviews and merges every open
sub-issue in dependency order, using fresh headless Claude Code and Codex agents. The vendor
that did not write a change reviews it. A run never waits for a person: the engine decides,
recovers, or parks an issue and carries on. See `docs/adr/0008-implement-loop.md` and
`docs/adr/0011-autonomous-implement-loop.md`.

The user hears from you twice: once to confirm the launch, once with the final report.

This skill body is checked in byte-identically at `.agents/skills/implement/SKILL.md` (Codex)
and `.claude/skills/implement/SKILL.md` (Claude Code); CI enforces the match. Implicit invocation
is disabled in both harnesses.

The argument is an issue number: an epic (all its open sub-issues) or a single issue (plus its
open prerequisites). Your operator name is `claude` if you are Claude Code, `codex` if you are Codex.

## 1. Preflight

Run `scripts/implement.sh doctor`. It repairs what it can on its own (browser tooling, the
browser's system libraries in user space, the pinned test runner) before reporting. If anything
is FAIL, stop and tell the user the exact fix in one line. A WARN means some deliverables cannot
be checked on this host; the run still goes ahead and parks only those. Mention each WARN in
one line.

## 2. Plan and confirm, in one message

Run `scripts/implement.sh plan <issue>`. In one short message, give: the number of work items
and waves, anything already closed, prerequisites pulled in from outside, and the plan's
warnings. Then state, and ask for one explicit yes:

- The run merges each pull request into `main` **by itself** once every gate passes: the
  engine's own verification, a cross-vendor review with no reproduced defect, and the
  `required` CI check green on the exact reviewed commit.
- It does not stop to ask anything. Where an issue is ambiguous, the judge decides and the
  decision is published in the pull request's "Decisions" section; the user overrides it after
  the fact by editing the issue (reopening it first if it is closed) and re-running.
- Anything only a person can provide (credentials agents do not hold, a rehearsal) is collected
  in one owner checklist at the end, never faked.
- There is no budget cap; each call's cost is logged.
- Agents run as the user, with GitHub credentials removed from their environment. That stops
  casual use, not a determined agent; for stronger isolation, run the loop in a container or VM.

Proceed only on an explicit yes in this conversation. This yes is the merge approval the `ship`
skill would otherwise ask for, for every PR of this run.

## 3. Launch, then wait

```sh
scripts/implement.sh run <issue> --operator <claude|codex> --yes
```

- Claude Code: run it with the Bash tool in the background. You are notified when it exits; do
  not poll. If the user asks for progress meanwhile, run `scripts/implement.sh status <issue>`
  once and answer in two lines.
- Codex: the engine needs network access (GitHub and both agent CLIs) and starts its own
  agents, so it cannot run inside your default sandbox. Run it with escalated permissions if
  your approval mode allows, or ask the user to run the exact command in a terminal.

A run for the same issue resumes where it stopped; `--fresh` starts over and is used only when
the user asks for it.

## 4. Report, once

When the run exits, read `scripts/implement.sh status <issue>` and the run summary comment on
the root issue. Then:

1. If the main checkout is clean and on `main`, update it (`git pull --ff-only`) so the user
   sees the merged work locally; otherwise say it is behind and why.
2. Send one message, facts only:
   - **Done**: issues closed, with their PR numbers.
   - **Decisions**: how many the loop took, and where to read them (each PR's Decisions section).
   - **Owner checklist**: every item only a person can provide, in one block, each with the
     issue link and, where a command is involved, the exact command. Run every command (or its
     `--help`) yourself before handing it over.
   - **Parked**: each issue, why, and what resumes it (see the progress comment on the issue).
     Engine faults are already filed as `loop:engine-bug` issues; give their links.
   - Cost: the status line's call count and Claude cost.

Say what you read in the engine's state and events as fact; label anything else as a guess.

## Afterwards

If the user wants a parked issue tried again without editing it, `scripts/implement.sh retry
<root> [<issue>...]` and a re-run do that. Editing an issue and re-running also resumes it with
the new text. `scripts/implement.sh stop <issue>` stops a running run at its next safe point.

## Hard rules

- Never edit files in the run's worktrees, never commit, push, merge, edit issues or tick issue
  checkboxes yourself. The engine does all of that, with evidence.
- Never pass `--yes` without the user's explicit confirmation in this conversation.
- Never relay a question during a run, and never settle a point on the user's behalf by editing
  an issue: the engine decides and publishes its decisions.
- Never use `--no-verify`, `--force`, or any way around the git hooks, the ruleset or CI.
