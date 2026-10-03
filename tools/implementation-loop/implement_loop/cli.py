"""Command line: `implement plan|status|stop|record-fixture <issue>`.

`run` arrives with the live Claude Code and Codex adapters; until then the engine is exercised
by the test suite with scripted agents.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import VERSION, report
from .github import GhCli, RecordingGitHub
from .graph import CycleError, build_plan
from .state import RunStore


def repo_root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit("implement: run this inside the repository")
    return Path(out.stdout.strip())


def repo_slug() -> str:
    out = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit("implement: `gh repo view` failed; is the GitHub CLI authenticated (gh auth status)?")
    return out.stdout.strip()


def cmd_plan(args) -> int:
    root = repo_root()
    try:
        plan = build_plan(GhCli(args.repo or repo_slug()), args.issue, root)
    except CycleError as e:
        print(f"implement: {e}. Fix the blocked-by links before running.", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"root": plan.root, "mode": plan.mode, "work": plan.work, "waves": plan.waves,
                          "deps": {n: sorted(d) for n, d in plan.deps.items()}, "external": sorted(plan.external),
                          "closed_work": plan.closed_work, "warnings": plan.warnings}, indent=1))
    else:
        print(report.render_plan(plan))
    return 0


def cmd_status(args) -> int:
    store = RunStore.for_root(repo_root(), args.issue)
    issues = store.known()
    if not issues:
        print(f"No run recorded for #{args.issue}.")
        return 0
    for n in issues:
        st = store.issue(n)
        extra = f" · {st.reason}" if st.reason else ""
        print(f"#{n:<5} {st.phase.value:<12} attempts {st.attempts} · fix rounds {st.fix_rounds}"
              + (f" · PR #{st.pr}" if st.pr else "") + extra)
    print(f"\nRun directory: {store.dir}")
    return 0


def cmd_stop(args) -> int:
    store = RunStore.for_root(repo_root(), args.issue)
    (store.dir / "STOP").write_text("stop requested\n")
    print(f"Stop requested. The run for #{args.issue} finishes its current steps, saves, and exits.")
    return 0


def cmd_record(args) -> int:
    rec = RecordingGitHub(GhCli(args.repo or repo_slug()))
    build_plan(rec, args.issue, repo_root())
    rec.save(Path(args.out))
    print(f"Recorded {sum(len(v) for v in rec.fixture.values())} responses to {args.out}")
    return 0


def cmd_run(args) -> int:
    print("implement: `run` needs the live Claude Code and Codex adapters, which arrive in the next PR. "
          "Use `plan` to see what a run would do.", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="implement", description="Implement an epic or an issue, with evidence.")
    parser.add_argument("--version", action="version", version=f"implement-loop {VERSION}")
    parser.add_argument("--repo", help="owner/name (default: the current repo)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan", help="show what a run would do (read-only)")
    p.add_argument("issue", type=int)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plan)
    p = sub.add_parser("status", help="show a run's progress")
    p.add_argument("issue", type=int)
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("stop", help="ask a running run to stop at the next safe point")
    p.add_argument("issue", type=int)
    p.set_defaults(func=cmd_stop)
    p = sub.add_parser("run", help="run the loop (arrives with the live adapters)")
    p.add_argument("issue", type=int)
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("record-fixture", help="record GitHub reads for offline tests")
    p.add_argument("issue", type=int)
    p.add_argument("out")
    p.set_defaults(func=cmd_record)
    args = parser.parse_args(argv)
    return args.func(args)
