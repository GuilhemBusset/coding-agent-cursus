---
name: implement
description: Implement a GitHub epic or issue end to end with the implement loop (a builder plans and builds, the other vendor examines, probes and certifies, evidence-gated merges), autonomously from launch to final report. Invoke explicitly with /implement <issue> (Claude Code) or $implement <issue> (Codex). Do not invoke implicitly.
compatibility: Requires git, Python 3.11+, an authenticated GitHub CLI (gh), and both the Claude Code and Codex CLIs
disable-model-invocation: true
allowed-tools: Bash, Read
---

# implement — run the implement loop on an epic or an issue

You are the **operator**: you launch the loop and you report its result. You do not do the work,
and you do not relay questions. A deterministic engine (`tools/implementation-loop/`) works every
open sub-issue in dependency order with fresh headless agents: the **builder** (your vendor) plans
and builds each issue with its own tests; the **examiner** (the other vendor) triages the plan,
examines and probes the exact commit, decides the builder's requests and certifies what lands. A
**supervisor** keeps running the engine until every issue is settled, so nothing waits for a
person and nothing is parked. See `docs/adr/0012-builder-examiner-loop.md`.

The user hears from you twice: once to confirm the launch, once with the final report.

This skill body is checked in byte-identically at `.agents/skills/implement/SKILL.md` (Codex)
and `.claude/skills/implement/SKILL.md` (Claude Code); CI enforces the match. Implicit invocation
is disabled in both harnesses.

The argument is an issue number: an epic (all its open sub-issues) or a single issue (plus its
open prerequisites). Your operator name is `claude` if you are Claude Code, `codex` if you are Codex.

## 1. Preflight

Run `scripts/implement.sh doctor`. It repairs what it can on its own (browser tooling, the
browser's system libraries in user space, the pinned test runner) before reporting. If anything
is FAIL, stop and tell the user the exact fix in one line. Mention each WARN in one line.

## 2. Plan and confirm, in one message

Run `scripts/implement.sh plan <issue>`. In one short message, give: the number of work items
and waves, anything already closed, prerequisites pulled in from outside, and the plan's
warnings. Then state, and ask for one explicit yes:

- The loop merges each pull request into `main` **by itself** once every gate passes: the
  verifier on the exact commit, the other vendor's certificate for that exact commit, and the
  `required` CI check green on it.
- It does not stop to ask anything. Ambiguities are decided and published in each PR's
  "Decisions" section; the user overrides one after the fact by editing the issue and re-running.
- Items that need something this host lacks (a laptop, a rehearsal, another account or OS, an API
  key) are delivered as far as agents can take them and listed as owner obligations. An item that
  needs another open issue waits for it (in an epic, that issue may join the run) or is deferred
  and reopens by itself when that issue lands. Nothing is faked.
- Each issue has a persistent call ceiling (S 20, M 30, L 45); an issue that cannot be delivered
  within it ends `failed`, is filed as a loop fault, and is retried once by the next engine version.
- The supervisor keeps running for at most 10 runs and 24 hours. It may run one repair run per
  loop fault on the engine itself, never on its safety surface (the gates, the verifier, CI).
- Agents run as the user, with GitHub credentials removed from their environment, both vendors
  with the same access. That stops casual use, not a determined agent; for stronger isolation,
  run the loop in a container or VM.

Proceed only on an explicit yes in this conversation. This yes is the merge approval the `ship`
skill would otherwise ask for, for every PR of this supervision.

## 3. Launch, then wait

```sh
scripts/implement.sh supervise <issue> --operator <claude|codex> --yes --detach
```

It prints the supervisor's pid and log, and keeps running if your session ends.

- Claude Code: wait for that pid in the background (`tail --pid=<pid> -f /dev/null` with the Bash
  tool's background mode); you are notified when it exits. Do not poll. If the user asks for
  progress meanwhile, run `scripts/implement.sh status <issue>` once and answer in two lines.
- Codex: the loop needs network access (GitHub and both agent CLIs) and starts its own agents, so
  it cannot run inside your default sandbox. Run it with escalated permissions if your approval
  mode allows, or ask the user to run the exact command in a terminal.

Supervising the same issue again resumes where it stopped; `scripts/implement.sh run <issue>
--fresh` starts over and is used only when the user asks for it.

## 4. Report, once

When the supervisor exits, read `scripts/implement.sh status <issue>`, the supervisor log, and the
run summary comment on the root issue. Then:

1. If the main checkout is clean and on `main`, update it (`git pull --ff-only`) so the user sees
   the merged work locally; otherwise say it is behind and why.
2. Send one message, facts only:
   - **Done / delivered**: issues merged, with their PR numbers.
   - **Decisions**: how many the loop took, and where to read them (each PR's Decisions section).
   - **Remaining obligations**: every owner item (with the issue link and, where a command is
     involved, the exact command; run it or its `--help` yourself first) and every deferred item
     with the issue it waits for.
   - **Waiting** (if the supervisor's bounds ran out first): each issue and what it waits for.
   - **Failed**: each issue, its cause, and the loop-fault issue filed for it.
   - **Follow-ups**: the follow-up issues filed for non-blocking findings.
   - Cost: the status line's call count and Claude cost.

Say what you read in the engine's state and events as fact; label anything else as a guess.

## Afterwards

`scripts/implement.sh retry <root> [<issue>...]` gives a failed issue a fresh ceiling (or resumes
a waiting one) on the next supervision. Editing an issue and re-running also resumes it with the
new text and fresh budgets. `scripts/implement.sh stop <issue>` stops a running run at its next
safe point.

## Hard rules

- Never edit files in the run's worktrees, never commit, push, merge, edit issues or tick issue
  checkboxes yourself. The engine does all of that, with evidence.
- Never pass `--yes` without the user's explicit confirmation in this conversation.
- Never relay a question during a run, and never settle a point on the user's behalf by editing
  an issue: the engine decides and publishes its decisions.
- Never use `--no-verify`, `--force`, or any way around the git hooks, the ruleset or CI.
