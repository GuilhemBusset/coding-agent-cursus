# Implement loop engine

The engine behind `/implement` (Claude Code), `$implement` (Codex) and `scripts/implement.sh`.
Give it an epic or a single issue; it works through every open sub-issue in dependency order,
without waiting for a person, until each issue is done, delivered with owner obligations, or
parked with a diagnosis. Design and rationale: [ADR 0008](../../docs/adr/0008-implement-loop.md)
and [ADR 0011](../../docs/adr/0011-autonomous-implement-loop.md).

It is plain Python (3.11+, standard library only) plus `git` and the authenticated GitHub CLI.
Agents (Claude Code and Codex, run headless) only produce proposals, patches and findings through
the `Agents` interface; the engine owns the issue graph, git, GitHub, the checks and the merges.

## Use

Normally through the skill: `/implement 10` (Claude Code) or `$implement 10` (Codex). It runs
the preflight, shows the plan, asks you once to confirm that the run merges its own PRs, starts
the engine in the background and reports when it ends. The same steps by hand:

```sh
scripts/implement.sh doctor [--smoke]                 # toolchain, logins, ruleset; repairs the browser tooling
scripts/implement.sh plan 10                           # order, waves, warnings (read-only)
scripts/implement.sh run 10 --operator claude --yes    # run; re-running resumes
scripts/implement.sh status 10                         # progress, cost so far
scripts/implement.sh stop 10                           # stop at the next safe point
scripts/implement.sh retry 10 [21 ...]                 # let parked issues try again on the next run
```

`--operator` names the agent driving the run (it designs and implements); the other one writes
the acceptance checks and reviews. `--yes` records that the user agreed the run merges its own
PRs once every gate passes.

## Live agents

Every agent call is a fresh headless process: `claude -p --output-format json --json-schema …`
or `codex exec --output-schema … -o …`, with the answer validated against the role's schema
(`implement_loop/schemas.py`), retried twice on failure, and recorded with its prompt, answer,
duration and cost under `<run dir>/calls/` and `agents.jsonl`. Prompts are in `prompts/`;
per-role effort, models and timeouts in `loop.toml`.

| Role | Access |
| --- | --- |
| explore, propose, audit, critique, judge, review | read-only tools (Claude) / read-only sandbox (Codex) |
| write_checks, implement | edit the issue worktree and run commands; Claude's commit, push and `gh` commands are denied, Codex cannot write `.git` |
| verify_finding | anything, in a disposable worktree deleted afterwards |

Those per-tool rules are a convenience, not the boundary. Agents run with no GitHub
credentials (tokens, SSH agent and git credential helpers are removed from their environment),
the engine undoes any commit an agent makes and commits the changes itself, and only verified,
reviewed heads are merged. Codex calls start with no MCP servers, agents' tags and branches are
deleted, and each worktree has a private copy of `setup/node_modules`.

**Known limit:** agents run as your user. Removing credentials from their environment stops
casual use, not an agent determined to read them from disk. For real isolation, run the loop
inside a container, a VM or a separate user account.

## How an issue moves

`pending → design → designed → checks → implement → verify → review → land → merged → delivered | done`, or `parked`

| Phase | Who | What happens |
| --- | --- | --- |
| design | both vendors, then a judge | Two blind proposals (one for small issues), a criteria audit by the other vendor, one critique round if they diverge, then a judge maps every ledger item to a check. The judge decides every ambiguity itself and publishes each decision in the PR. |
| designed | engine | Waits until its files don't overlap any issue being written, and no shared file is held. |
| checks | other vendor | Writes executable acceptance checks. The engine commits them first and locks them by hash. |
| implement | operator vendor | Edits its own worktree. Never commits. May report a locked check as defective (the other vendor tries to reproduce it; if it does, the check's author amends it) or the design as impossible (it is redone once). Edits to locked checks are reverted before the engine commits. |
| verify | engine | Runs the checks from the engine's own code: locked files unchanged, no new test configuration, every expected test ran, no skips, only declared files changed. |
| review | both vendors | Cross-vendor, acceptance and (for HTML) visual reviewers in parallel. Findings are re-verified; a reproduced defect sends the issue back, whatever its priority. |
| land | engine | One at a time: push without force, PR with `Refs #N`, evidence comment, wait for the `required` check on the exact head, merge with that head SHA. A red check is re-run once, then its log goes back to the implementer. |
| merged → delivered/done | engine | Re-verifies on `main`, re-runs the run's earlier issues' checks there, ticks the checkboxes with evidence links, and closes the issue. With items only a person can provide it stays open as delivered; once the owner ticks them, the next run closes it. |

Recovery, in order, each bounded: 3 implement-verify attempts, 2 review fix rounds, 2 check
amendments, 2 CI fix rounds, then one redesign that keeps the work already written; after a
merge, one fix-forward round. When they run out the issue is **parked** with a diagnosis on the
issue, issues that depend on it are parked with it, and independent work carries on. What
resumes a parked issue on a later run depends on why it parked: a fixed environment, the end of
an outage, a new engine version for an engine fault (filed once as a `loop:engine-bug` issue),
an edit to the issue, or `retry`. Limits survive restarts; only an edit to the issue (new
evidence) grants a fresh set.

## Where things live

- Worktrees: `<repo parent>/<repo name>.loop/issue-<root>/` (`coord/` plus one per active issue).
- Run state: `<git common dir>/implementation-loop/issue-<root>/` (`state.json`, `events.jsonl`,
  per-issue evidence). Re-running resumes; a `STOP` file there stops the run.
- Repo-wide claims (merge queue): `<git common dir>/implementation-loop/claims/`.
- Engine faults waiting to be filed, deduplicated by fingerprint: `<git common dir>/implementation-loop/faults.json`.
- The browser's user-space system libraries, if the doctor had to fetch them: `<git common dir>/implementation-loop/browser-libs/`.

## Tests

```sh
python3 -m unittest discover -s tools/implementation-loop/tests -t tools/implementation-loop/tests
```

The end-to-end tests drive the real engine, real git, `scripts/ship.sh`, the verifier and real
squash merges into a throwaway bare remote; only the agents and GitHub are fakes.
`tests/fixtures/epic10.json` is a recording of epic #10 (`scripts/implement.sh record-fixture 10 <file>`).
The pytest-specific verifier tests are skipped when pytest is not installed.
