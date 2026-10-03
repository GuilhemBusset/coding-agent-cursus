"""Command line: `implement doctor | plan | run | status | stop | record-fixture`."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import VERSION, report
from .config import Config
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
    calls = store.dir / "agents.jsonl"
    if calls.exists():
        records = [json.loads(line) for line in calls.read_text().splitlines() if line.strip()]
        cost = sum(r.get("cost_usd") or 0 for r in records)
        tokens = sum(((r.get("usage") or {}).get("input_tokens") or 0) + ((r.get("usage") or {}).get("output_tokens") or 0)
                     for r in records if r.get("vendor") == "codex")
        print(f"\nAgent calls: {len(records)} · Claude cost ${cost:.2f} · Codex tokens {tokens:,}")
    running = (store.dir / "lock").exists()
    print(f"Run directory: {store.dir}" + (" (a run is active)" if running else ""))
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


def detect_operator() -> str | None:
    """Claude Code sets CLAUDECODE=1 for the commands it runs. Codex has no stable marker (and the
    Codex plugin for Claude Code sets CODEX_* variables), so Codex runs pass --operator codex."""
    return "claude" if os.environ.get("CLAUDECODE") == "1" else None


def _out(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return p.returncode, (p.stdout or p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def doctor_checks(root: Path, slug: str | None) -> list[tuple[str, str, str]]:
    """(status, name, detail) with status PASS, WARN or FAIL."""
    checks = []

    def add(ok, name, detail, warn_only=False):
        checks.append(("PASS" if ok else ("WARN" if warn_only else "FAIL"), name, detail))

    add(sys.version_info >= (3, 11), "python", sys.version.split()[0])
    code, out = _out(["git", "--version"])
    add(code == 0, "git", out)
    code, out = _out(["gh", "auth", "status"])
    add(code == 0, "gh auth", "authenticated" if code == 0 else out[-200:])
    add(bool(slug), "repository", slug or "gh repo view failed")
    for cli, version_cmd in (("claude", ["claude", "--version"]), ("codex", ["codex", "--version"])):
        found = shutil.which(cli)
        code, out = _out(version_cmd) if found else (1, "not found on PATH")
        add(code == 0, cli, out.splitlines()[0] if out else "")
    code, out = _out(["codex", "login", "status"])
    add(code == 0, "codex login", out.splitlines()[0] if out else "")
    if slug:
        code, out = _out(["gh", "api", f"repos/{slug}/rulesets", "--jq", ".[].id"])
        required = False
        for rid in out.split() if code == 0 else []:
            c2, o2 = _out(["gh", "api", f"repos/{slug}/rulesets/{rid}"])
            required |= c2 == 0 and '"context":"required"' in o2.replace(" ", "")
        add(required, "required check", "the ruleset requires `required`" if required else
            "the ruleset does not require `required`; run setup/apply-ruleset.sh", warn_only=True)
    node_modules = (root / "setup" / "node_modules").is_dir()
    add(node_modules, "html tooling", "setup/node_modules present" if node_modules else
        "missing: HTML deliverables cannot be checked; run node setup/html-pages.mjs", warn_only=True)
    return checks


def cmd_doctor(args) -> int:
    root = repo_root()
    code, slug = _out(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    checks = doctor_checks(root, args.repo or (slug if code == 0 else None))
    for status, name, detail in checks:
        print(f"{status:<5} {name:<15} {detail}")
    failed = [c for c in checks if c[0] == "FAIL"]
    if args.smoke and not failed:
        from .live import LiveAgents
        from .workspace import Workspace
        scratch = runs_dir(root) / "smoke"
        agents = LiveAgents("claude", scratch, Workspace(root, 0, root / "scripts" / "ship.sh"))
        for vendor in ("claude", "codex"):
            try:
                agents.call(vendor, "explore", root, 'Do not use any tool. Return {"notes": "ok"}.')
                print(f"PASS  smoke {vendor:<9} a structured call worked")
            except Exception as e:  # noqa: BLE001 - report any failure of the live call
                print(f"FAIL  smoke {vendor:<9} {e}")
                failed.append(("FAIL", vendor, str(e)))
    return 1 if failed else 0


def runs_dir(root: Path) -> Path:
    from .state import runs_root
    return runs_root(root)


def cmd_run(args) -> int:
    from .engine import Engine
    from .live import LiveAgents
    from .workspace import Workspace

    root = repo_root()
    operator = args.operator or detect_operator()
    if operator not in ("claude", "codex"):
        sys.exit("implement: say who is driving this run with --operator claude or --operator codex")
    slug = args.repo or repo_slug()
    failed = [c for c in doctor_checks(root, slug) if c[0] == "FAIL"]
    if failed:
        for status, name, detail in failed:
            print(f"{status} {name}: {detail}", file=sys.stderr)
        sys.exit("implement: fix the failed checks above (scripts/implement.sh doctor) before running")
    gh = GhCli(slug)
    try:
        plan = build_plan(gh, args.issue, root)
    except CycleError as e:
        sys.exit(f"implement: {e}. Fix the blocked-by links before running.")
    print(report.render_plan(plan))
    if not args.yes:
        if not sys.stdin.isatty():
            sys.exit("implement: confirm with --yes once the user has agreed that this run merges its own PRs")
        answer = input("\nThis run merges each PR into main itself once every gate passes. Proceed? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            return 1
    store = RunStore.for_root(root, args.issue, fresh=args.fresh)
    log_file = store.dir / "engine.log"

    def log(message: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
        print(line, flush=True)
        with log_file.open("a") as f:
            f.write(line + "\n")

    ws = Workspace(root, args.issue, root / "scripts" / "ship.sh")
    agents = LiveAgents(operator, store.dir, ws)
    log(f"run for #{args.issue}: operator {operator}, reviewer {agents.other}, {len(plan.work)} work item(s)")
    engine = Engine(plan, store, gh, ws, agents, Config(repo=slug), repo_root=root, log=log)
    summary = engine.run()
    log("finished: " + json.dumps(summary, default=str))
    return 0 if not summary["needs_human"] and not summary["blocked_by_needs_human"] else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="implement", description="Implement an epic or an issue, with evidence.")
    parser.add_argument("--version", action="version", version=f"implement-loop {VERSION}")
    parser.add_argument("--repo", help="owner/name (default: the current repo)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("doctor", help="check the toolchain a run needs")
    p.add_argument("--smoke", action="store_true", help="also make one tiny structured call to each CLI (costs cents)")
    p.set_defaults(func=cmd_doctor)
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
    p = sub.add_parser("run", help="run the loop on an epic or issue (resumes an existing run)")
    p.add_argument("issue", type=int)
    p.add_argument("--operator", choices=["claude", "codex"], help="the agent driving this run (the other one reviews)")
    p.add_argument("--yes", action="store_true", help="the user confirmed that this run merges its own PRs")
    p.add_argument("--fresh", action="store_true", help="archive the previous run state and start over")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("record-fixture", help="record GitHub reads for offline tests")
    p.add_argument("issue", type=int)
    p.add_argument("out")
    p.set_defaults(func=cmd_record)
    args = parser.parse_args(argv)
    return args.func(args)
