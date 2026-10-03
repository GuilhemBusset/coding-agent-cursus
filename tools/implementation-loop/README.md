# Implement loop engine

The engine behind `/implement` (Claude Code), `$implement` (Codex) and `scripts/implement.sh`.
Give it an epic or a single issue; it works through every open sub-issue in dependency order and
stops only when each acceptance criterion has evidence. Design and rationale:
[ADR 0008](../../docs/adr/0008-implement-loop.md).

It is plain Python (3.11+, standard library only) plus `git` and the authenticated GitHub CLI.
Agents (Claude Code and Codex, run headless) only produce proposals, patches and findings through
the `Agents` interface; the engine owns the issue graph, git, GitHub, the checks and the merges.

## Use

```sh
scripts/implement.sh plan 10      # what a run on #10 would do: order, waves, warnings (read-only)
scripts/implement.sh status 10    # progress of the run for #10
scripts/implement.sh stop 10      # ask that run to stop at its next safe point
```

`run` needs the live Claude Code and Codex adapters and is not available yet.

## How an issue moves

`pending → design → designed → checks → implement → verify → review → land → merged → accepted → done`

| Phase | Who | What happens |
| --- | --- | --- |
| design | both vendors, then a judge | Two blind proposals (one for small issues), a criteria audit by the other vendor, one critique round if they diverge, then a judge maps every ledger item to a check. |
| designed | engine | Waits until its files don't overlap any issue being written, and no shared file is held. |
| checks | other vendor | Writes executable acceptance checks. The engine commits them first and locks them by hash. |
| implement | operator vendor | Edits its own worktree. Never commits; has an explicit "impossible" exit. |
| verify | engine | Runs the checks from the engine's own code: locked files unchanged, no new test configuration, every expected test ran, no skips, only declared files changed. |
| review | both vendors | Cross-vendor, acceptance and (for HTML) visual reviewers in parallel. Findings are re-verified; a reproduced defect sends the issue back, whatever its priority. |
| land | engine | One at a time: push without force, PR with `Refs #N`, evidence comment, wait for the `required` check on the exact head, merge with that head SHA. |
| merged → accepted/done | engine | Re-verifies on `main`, ticks the issue's checkboxes with evidence links, closes it unless a person must provide some evidence. |

Caps: 2 design rounds, 3 implement-verify attempts, 2 fix rounds, and the same blocker 3 times.
Hitting one ends that issue in `needs_human`; independent work carries on.

## Where things live

- Worktrees: `<repo parent>/<repo name>.loop/issue-<root>/` (`coord/` plus one per active issue).
- Run state: `<git common dir>/implementation-loop/issue-<root>/` (`state.json`, `events.jsonl`,
  per-issue evidence). Re-running resumes; a `STOP` file there stops the run.
- Repo-wide claims (merge queue): `<git common dir>/implementation-loop/claims/`.

## Tests

```sh
python3 -m unittest discover -s tools/implementation-loop/tests -t tools/implementation-loop/tests
```

The end-to-end tests drive the real engine, real git, `scripts/ship.sh`, the verifier and real
squash merges into a throwaway bare remote; only the agents and GitHub are fakes.
`tests/fixtures/epic10.json` is a recording of epic #10 (`scripts/implement.sh record-fixture 10 <file>`).
The pytest-specific verifier tests are skipped when pytest is not installed.
