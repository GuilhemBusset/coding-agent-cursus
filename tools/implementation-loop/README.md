# Implement loop engine

The engine behind `/implement` (Claude Code), `$implement` (Codex) and `scripts/implement.sh`.
Give it an epic or a single issue; it works through every open sub-issue in dependency order,
without waiting for a person and without parking, until each issue is done, delivered with
typed obligations, or (rarely, and visibly) failed. Design and rationale:
[ADR 0008](../../docs/adr/0008-implement-loop.md), [ADR 0011](../../docs/adr/0011-autonomous-implement-loop.md)
and [ADR 0012](../../docs/adr/0012-builder-examiner-loop.md).

It is plain Python (3.11+, standard library only) plus `git` (2.29 or later, for
`git init --object-format`) and the authenticated GitHub CLI.
Agents (Claude Code and Codex, run headless) only produce plans, code, tests, probes, findings and
decisions through the `Agents` interface; the engine owns the issue graph, git, GitHub, the
verifier, the gates and the merges.

## Use

Normally through the skill: `/implement 10` (Claude Code) or `$implement 10` (Codex). It runs
the preflight, shows the plan, asks you once to confirm that the runs merge their own PRs, starts
the supervisor in the background and reports when it ends. The same steps by hand:

```sh
scripts/implement.sh doctor [--smoke]                 # toolchain, logins, ruleset; repairs the browser tooling
scripts/implement.sh plan 10                           # order, waves, warnings (read-only)
scripts/implement.sh supervise 10 --operator claude --yes --detach   # run until settled (bounded)
scripts/implement.sh run 10 --operator claude --yes    # one engine run; re-running resumes
scripts/implement.sh status 10                         # progress, cost so far
scripts/implement.sh stop 10                           # stop at the next safe point
scripts/implement.sh retry 10 [21 ...]                 # a fresh ceiling for failed issues, resume waiting ones
```

`--operator` names the agent driving the run (the builder); the other one is the examiner.
`--yes` records that the user agreed the runs merge their own PRs once every gate passes.

## Live agents

Every agent call is a fresh headless process: `claude -p --output-format json --json-schema …`
or `codex exec --output-schema … -o …`, with the answer validated against the role's schema
(`implement_loop/schemas.py`), retried twice on failure, and recorded with its prompt, answer,
duration and cost under `<run dir>/calls/` and `agents.jsonl`. Prompts are in `prompts/`;
per-role effort, models and timeouts in `loop.toml`.

| Role | Vendor | Access |
| --- | --- | --- |
| explore, plan, triage, arbitrate | builder (explore, plan) / examiner (triage, arbitrate) | read-only tools (Claude) / read-only sandbox (Codex) |
| build | builder | edits the issue worktree, runs anything, network; Claude's commit, push and `gh` commands are denied |
| resolve_locked | examiner | resolves main's conflicts in locked tests, in the issue worktree |
| examine, decide | examiner | anything, network and a browser, in a disposable worktree deleted afterwards |

Both vendors' working roles have the same access: Codex runs them with `--sandbox
danger-full-access`, like Claude Code without a sandbox (ADR 0012). Every attempt is reported to
the engine's meter: an answer is charged to the issue's call ceiling, a timeout or crash to its
infrastructure budget, and an outage (the CLI could not reach its service) to neither: the issue
waits for the supervisor to see the vendor answer again.

Those per-tool rules are a convenience, not the boundary. Agents run with no GitHub
credentials (tokens, SSH agent and git credential helpers are removed from their environment),
an agent's commits never reach the repository (the engine commits its changes itself), and only verified,
reviewed heads are merged. Codex calls start with no MCP servers, and each worktree has a private
copy of `setup/node_modules`.

Every agent that can write (`build`, `resolve_locked`, and `examine` and `decide` in their
disposable worktree) works against a private git directory of its run's own, at
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
  working tree is kept, and the engine commits it. Index entries the working tree cannot rebuild,
  committed or not, are carried into the worktree's index with their blobs, so the engine's
  commit includes them: ignored paths the agent staged (`git add -f`), and executable bits it
  recorded only in the index (`git update-index --chmod`, the only record of the bit under
  `core.fileMode=false`). An entry the agent's index records as the worktree's index already
  does is left alone; every other path is committed from the working tree.
- `agent_merge_dropped`: main's merge was in progress, and the agent aborted, quit or reset it
  without committing it. The engine ends the merge too, keeping the files, so the conflict goes
  back to its author (`conflict_unresolved`, `check_conflict_unresolved`).
- `issue_branch_moved_externally`: someone outside the agent moved the issue's branch during
  the call. The agent could not have, so the engine leaves it as it is.

The engine never changes the repository's config for this. If a run is killed mid-call, the
worktree still names the private directory. The next time the engine uses or removes the
worktree, it points the `.git` file back at the directory git registered for it, carries the
index entries above (this needs no HEAD, so it also works when the branch was deleted), and
deletes the private one. If carrying fails, the worktree is left on the private directory, kept
whole, and the next use tries again, so staged work is never dropped. **Limit:** a git command the agent points at another checkout (`git -C /elsewhere`)
runs outside this boundary. Its ref changes are neither isolated nor removed.

**Known limit:** agents run as your user. Removing credentials from their environment stops
casual use, not an agent determined to read them from disk. For real isolation, run the loop
inside a container, a VM or a separate user account.

## How an issue moves

`pending → plan → planned → build → verify → examine → land → merged → delivered | done`, with
`waiting` (resumes by itself) and `failed` (explicit non-delivery) instead of parking.

| Phase | Who | What happens |
| --- | --- | --- |
| plan | builder, then engine, then examiner | The builder reads the repo and the issue's branch and gives every ledger item a quoted reading and a proof kind (`test`, `command`, `review`, `owner` for a capability the host lacks, `deferred` to another open issue), plus its zones. The engine lints it (one free retry, then it repairs it and publishes why). The examiner may only object to a misreading, a classification or a dependency, each with a quote; a classification dispute goes to the arbiter. |
| planned | engine | Waits until its zones don't overlap any issue being built, and no shared file is held. |
| build | builder | Writes the code, its own tests, the registrations and one or more commands per item (all of them run; after the first examination a changed list for an item is one `command_change` request). Never commits. Asks for anything outside its lane with a typed request (`paths`, `protected_change`, `command_change`, `test_change`, `reclassify`, `depends`, `dispute`), decided by a fresh call of the other vendor (disputes: the arbiter). Edits to locked tests without an approved request are reverted. |
| verify | engine | Runs every command and adopted probe from its own code: locked files unchanged, tests that ran before still run, no skips, per-process pytest reports, unselected tests need a disposition, changed files within the zones and approved grants, open findings re-run. |
| examine | examiner | In a disposable copy of the exact head: verdicts on review items, every finding at once (with memory of earlier rounds), probes, and a certificate. A finding blocks only if the engine reproduces it and it quotes the item or names a safety invariant; others become a follow-up issue. At the first examination the tests, their configuration, the selection manifest and the adopted probes lock. |
| land | engine | One at a time across runs (a run that finds the queue held waits): push without force, PR with `Refs #N`, evidence comment, the `required` check on the exact certified head, merge with that head SHA. Main moving means verify and a delta examination again. |
| merged → delivered/done | engine | Re-verifies on `main`, re-runs the run's earlier issues' checks there, ticks the checkboxes with evidence links, files the follow-up issue, and closes the issue, or keeps it open as delivered with its owner and deferred obligations. A broken `main` gets one fix-forward, then a revert PR. |

Budgets: a persistent per-issue call ceiling (S 20, M 30, L 45; infra ×1.5), an infrastructure
budget of 10 failed attempts, and the progress rule (two rounds that change nothing bring a
replan on the branch, two more end the issue `failed`). Conflicts with `main` cost no round. A
`failed` issue is filed as a loop fault and revived once, with a fresh ceiling, by the next
engine version. `scripts/implement.sh supervise` keeps running the engine (at most 10 runs and 24
hours), waits out outages, runs one repair run per loop fault (never on the safety surface listed
in `config.py`), and reopens deferred items once their issue lands.

## Keeping up with `main`

Other issues land while one is in flight, so the engine brings every issue branch up to date
with `main` by merging it in (never a rebase: that would rewrite verified, reviewed or published
commits), at two points:

- **Before each build round.** A clean merge is committed and recorded as
  `updated_from_main`. On a conflict the merge stays in progress for that round: the builder
  gets the conflict markers and feedback naming the files, and may change them that round.
  Conflicts in locked tests go to the other vendor (`resolve_locked`) first. The engine then
  concludes the merge, or aborts it if markers remain (`conflict_unresolved`) and the next round
  tries again.
- **At land, before pushing.** A clean merge makes a new head, so the issue is verified and
  certified again (a delta examination) before it may land. A conflict, there or in
  `scripts/ship.sh`, is aborted and sends the issue back to build (`conflict`).

A conflict is work for the builder, never an engine fault, and costs no round: main moving is
nobody's design fault (ADR 0012); the conflicted files join the issue's grants.
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
issue starts a new round on a new branch from `main` (`branch_restore_failed`); the branch is
never pointed at `main` or at a guess.

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
