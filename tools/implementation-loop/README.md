# Implement loop engine

The engine behind `/implement` (Claude Code), `$implement` (Codex) and `scripts/implement.sh`.
Give it an epic or a single issue; it works through every open sub-issue in dependency order,
without waiting for a person, until each issue is done, delivered with owner obligations, or
parked with a diagnosis. Design and rationale: [ADR 0008](../../docs/adr/0008-implement-loop.md)
and [ADR 0011](../../docs/adr/0011-autonomous-implement-loop.md).

It is plain Python (3.11+, standard library only) plus `git` (2.29 or later, for
`git init --object-format`) and the authenticated GitHub CLI.
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
an agent's commits never reach the repository (the engine commits its changes itself), and only verified,
reviewed heads are merged. Codex calls start with no MCP servers, and each worktree has a private
copy of `setup/node_modules`.

Every agent that can write (`write_checks`, `implement`, and `verify_finding` in its disposable
worktree) works against a private git directory of its run's own, at
`<repo parent>/<repo name>.loop/issue-<root>/agent-git/<id>/`. For the call, the worktree's `.git`
file names that directory instead of the worktree's own one in the shared repository. The
private directory starts as a copy of the worktree's git state: every ref, HEAD, the index, a
merge in progress, `info/` and the shared and per-worktree config. It reaches the shared objects
through an alternate, its `hooks` link to the shared hooks directory, and `core.hooksPath` still
applies, so the usual hooks fire. Every git process run in the worktree uses it, whatever the
agent's CLI does to the environment. Nothing the agent does to git, whether commits, checkouts,
branches, tags or ref deletions, changes the shared repository, so nothing has to be undone, and
refs another run or a person changes during the call are never touched. When the call ends, the
original `.git` file is put back, the private directory is deleted, and its state is reported:

- `agent_refs_deleted`: refs the agent created. They are gone with the private directory.
- `agent_ref_changes_discarded`: existing refs the agent moved or deleted. They never changed in
  the repository.
- `agent_commits_absorbed`, `agent_checkout_undone`: the agent committed, or switched branches
  or detached HEAD. The worktree stays on the issue's branch at its earlier head, the agent's
  working tree is kept, and the engine commits it. Ignored paths the agent staged (`git add -f`,
  committed or not) are carried into the worktree's index with their blobs, so the engine's
  commit includes them; every other path is committed from the working tree.
- `agent_merge_dropped`: main's merge was in progress, and the agent aborted, quit or reset it
  without committing it. The engine ends the merge too, keeping the files, so the conflict goes
  back to its author (`conflict_unresolved`, `check_conflict_unresolved`).
- `issue_branch_moved_externally`: someone outside the agent moved the issue's branch during
  the call. The agent could not have, so the engine leaves it as it is.

The engine never changes the repository's config for this. If a run is killed mid-call, the
worktree still names the private directory. The next time the engine uses or removes the
worktree, it points the `.git` file back at the directory git registered for it and deletes the
private one. **Limit:** a git command the agent points at another checkout (`git -C /elsewhere`)
runs outside this boundary. Its ref changes are neither isolated nor removed.

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

## Keeping up with `main`

Other issues land while one is in flight, so the engine brings every issue branch up to date
with `main` by merging it in (never a rebase: that would rewrite verified, reviewed or published
commits), at two points:

- **Before each implement round.** A clean merge is committed and recorded as
  `updated_from_main`. On a conflict the merge stays in progress for that round: the implementer
  gets the conflict markers and feedback naming the files, and may change them that round.
  Conflicts in locked checks go to their author, the other vendor, first. The engine then
  concludes the merge, or aborts it if markers remain (`conflict_unresolved`) and the next round
  tries again.
- **At land, before pushing.** A clean merge makes a new head, so the issue is verified and
  reviewed again before it may land. A conflict, there or in `scripts/ship.sh`, is aborted and
  sends the issue back to implement (`conflict`).

A conflict is work for the implementer, never an engine fault: each conflict episode costs one
review fix round, so conflicts that keep coming end in a redesign and then a park as exhausted.
Locked files that `main`'s merge changed are locked again at their merged digests
(`checks_relocked`). Only a change from the branch's own pre-merge tree counts, and only where
that tree still matched the lock: a check or test configuration the branch had already changed
keeps its old lock, so verification still reports the tampering (`checks_not_relocked`). No worktree keeps an unfinished rebase or merge between steps, and when a
run starts it aborts any that an earlier failure left behind (`worktree_recovered`). The branch
keeps every commit.

A worktree whose branch ref was deleted from under it is repaired first, when the run starts:
the branch is recreated, create-only, at the newest commit of the worktree's own HEAD reflog that
shares history with `main` and contains every commit the engine recorded for the issue
(`branch_restored`). A recorded commit that a later recorded one rewrote no longer counts: when
shipping rebases an unpublished branch, the checks commit and the old reviewed head are left out
of the verified tip's history. The working tree and index are left as they are. Without such a commit the
issue is parked (`branch_restore_failed`); the branch is never pointed at `main` or at a guess.

## Several runs on one repository

Runs for different epics or issues may share a repository. Each has its own run state and
worktrees, and the shared git writes (fetches, ref updates, worktree changes, attaching an agent
call's private git directory) are serialized across threads, runs and processes by an flock on
`<git common dir>/implementation-loop/git.lock`, never held while an agent works. Two runs that
plan the same issue are not supported: the second one's worktree for it cannot be created.

## Where things live

- Worktrees: `<repo parent>/<repo name>.loop/issue-<root>/` (`coord/` plus one per active issue).
- Run state: `<git common dir>/implementation-loop/issue-<root>/` (`state.json`, `events.jsonl`,
  per-issue evidence). Re-running resumes; a `STOP` file there stops the run.
- Repo-wide claims (merge queue): `<git common dir>/implementation-loop/claims/`.
- The cross-run git lock: `<git common dir>/implementation-loop/git.lock`.
- The private git directories of agent calls in flight: `<repo parent>/<repo name>.loop/issue-<root>/agent-git/`.
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
