#!/usr/bin/env python3
"""Which checks a change can affect, and running them (docs/adr/0013-test-tiers-and-selection.md).

    python3 tools/test-impact/impact.py plan [--base REF] [--all] [--json]
    python3 tools/test-impact/impact.py run [--base REF] [--all]
    python3 tools/test-impact/impact.py github --base SHA --head SHA [--all]

`plan` prints what a change selects, `run` runs it (scripts/check-changed.sh), `github` writes
the selection to $GITHUB_OUTPUT for ci.yml's `changes` job. Locally the change is everything
since the merge base with REF (default origin/main): commits, staged, unstaged and untracked
files. In CI it is the pull request's `BASE...HEAD`. The rules live in impact.toml next to
this file. Standard library only.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAP = Path(__file__).with_name("impact.toml")
SUITES_DIR = "tools/html-pages/tests"
SUITE_SUFFIX = ".test.mjs"
PAGE_RE = re.compile(r"^(docs|sessions)/.*\.html?$", re.I)
MARKER = re.compile(r"""data-design-system\s*=\s*["']cursus["']""", re.I)
# What check-page.mjs resolves on a page: runtime assets, whose content matters, and link
# targets, of which only existence matters.
RUNTIME = re.compile(r"""\s(?:src|data|poster)\s*=\s*["']([^"'#?]+)|<link\b[^>]*?\shref\s*=\s*["']([^"'#?]+)""", re.I)
LINK = re.compile(r"""\shref\s*=\s*["']([^"'#?]+)""", re.I)


@functools.cache
def glob_re(pattern: str) -> re.Pattern[str]:
    """`*` stays inside one directory, `**` crosses directories (`a/**` matches `a/b/c`)."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def matches(path: str, patterns: list[str]) -> bool:
    return any(glob_re(p).match(path) for p in patterns)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


@dataclass
class Change:
    paths: set[str] = field(default_factory=set)    # added, modified, and the old side of renames
    gone: set[str] = field(default_factory=set)     # deleted, or renamed away


def parse_name_status(text: str) -> Change:
    change = Change()
    for line in text.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0]:
            continue
        status, names = parts[0], parts[1:]
        change.paths.update(names)
        if status.startswith(("D", "R")):
            change.gone.add(names[0])
    return change


def local_change(base: str) -> Change:
    merge_base = git("merge-base", base, "HEAD").strip()
    change = parse_name_status(git("diff", "--name-status", "-M", merge_base))
    change.paths.update(git("ls-files", "--others", "--exclude-standard").splitlines())
    return change


def pr_change(base: str, head: str) -> Change:
    return parse_name_status(git("diff", "--name-status", "-M", f"{base}...{head}"))


def load_map() -> dict:
    with MAP.open("rb") as f:
        return tomllib.load(f)


def discover_suites() -> list[str]:
    folder = ROOT / SUITES_DIR
    return sorted(f"{SUITES_DIR}/{p.name}" for p in folder.iterdir() if p.is_file() and p.name.endswith(SUITE_SUFFIX))


def discover_sessions() -> list[str]:
    return sorted(f"sessions/{p.parent.name}" for p in (ROOT / "sessions").glob("*/tests") if p.is_dir())


def discover_pages() -> list[str]:
    files = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    pages = []
    for name in sorted(set(files)):
        if not PAGE_RE.match(name):
            continue
        try:
            if MARKER.search((ROOT / name).read_text(encoding="utf-8")):
                pages.append(name)
        except FileNotFoundError:
            continue
    return pages


def references(page: str) -> tuple[set[str], set[str]]:
    """Repo-relative files a page loads (src, data, poster, <link href>) and links to (href)."""
    text = (ROOT / page).read_text(encoding="utf-8")
    runtime = {a or b for a, b in RUNTIME.findall(text)}
    return resolve(page, runtime), resolve(page, set(LINK.findall(text)) - runtime)


def resolve(page: str, values: set[str]) -> set[str]:
    folder = (ROOT / page).parent
    found = set()
    for value in values:
        if re.match(r"^[a-z][a-z0-9+.-]*:", value, re.I) or value.startswith("//"):
            continue
        target = os.path.normpath(folder / value)
        try:
            found.add(Path(target).relative_to(ROOT).as_posix())
        except ValueError:
            continue
    return found


@dataclass
class Plan:
    everything: bool = False
    reasons: list[str] = field(default_factory=list)
    units: set[str] = field(default_factory=set)        # repo-config, ship, turn-in, engine
    sessions: list[str] = field(default_factory=list)
    suites: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"everything": self.everything, "reasons": self.reasons, "units": sorted(self.units),
                "sessions": self.sessions, "suites": self.suites, "pages": self.pages}


def select(change: Change, rules: dict | None = None, suites: list[str] | None = None,
           sessions: list[str] | None = None, pages: list[str] | None = None, everything: bool = False,
           refs: dict[str, tuple[set[str], set[str]]] | None = None) -> Plan:
    rules = rules if rules is not None else load_map()
    suites = suites if suites is not None else discover_suites()
    sessions = sessions if sessions is not None else discover_sessions()
    pages = pages if pages is not None else discover_pages()
    units = {name: unit["paths"] for name, unit in rules.get("units", {}).items()}
    node = rules.get("node", {})
    mapped = node.get("suites", {})
    plan = Plan()

    def full(reasons: list[str]) -> Plan:
        return Plan(True, reasons, set(units), list(sessions), list(suites), list(pages))

    reasons = ["--all"] if everything else []
    reasons += [f"{path} runs everything" for path in sorted(change.paths) if matches(path, rules["all"]["paths"])]
    if reasons:
        return full(reasons)

    chosen_suites, chosen_pages, chosen_sessions = set(), set(), set()
    # A suite the map does not know runs on every change.
    chosen_suites.update(s for s in suites if Path(s).name[:-len(SUITE_SUFFIX)] not in mapped)
    page_refs = refs if refs is not None else {page: references(page) for page in pages}
    for path in sorted(change.paths):
        hit = matches(path, rules["none"]["paths"])
        for name, patterns in units.items():
            if matches(path, patterns):
                plan.units.add(name)
                hit = True
        for session in sessions:
            if path.startswith(session + "/") or matches(path, rules["sessions"]["shared"]):
                chosen_sessions.add(session)
                hit = True
        if matches(path, node.get("shared", [])):
            chosen_suites.update(suites)
            hit = True
        for suite in suites:
            name = Path(suite).name[:-len(SUITE_SUFFIX)]
            if path == suite or matches(path, mapped.get(name, [])):
                chosen_suites.add(suite)
                hit = True
        if matches(path, rules["pages"]["shared"]):
            chosen_pages.update(pages)
            hit = True
        for page, (loads, links) in page_refs.items():
            if path == page or path in loads or (path in change.gone and path in links):
                chosen_pages.add(page)
                hit = True
        if path in change.gone:
            # A deleted page is no longer checked; pages that pointed at it are, above.
            hit = True
        if not hit:
            plan.reasons.append(f"{path} is in no rule of impact.toml")
    if plan.reasons:
        return full(plan.reasons)
    plan.sessions = sorted(chosen_sessions)
    plan.suites = sorted(chosen_suites)
    plan.pages = sorted(chosen_pages - change.gone)
    return plan


def describe(plan: Plan) -> str:
    lines = []
    if plan.everything:
        lines.append("Everything runs: " + "; ".join(plan.reasons))
    lines.append("units: " + (", ".join(sorted(plan.units)) or "none"))
    lines.append("sessions: " + (", ".join(plan.sessions) or "none"))
    lines.append(f"node suites ({len(plan.suites)}): " + (", ".join(Path(s).name for s in plan.suites) or "none"))
    lines.append(f"pages ({len(plan.pages)}): " + (", ".join(plan.pages) or "none"))
    return "\n".join(lines)


def commands(plan: Plan) -> list[tuple[str, list[str], Path]]:
    """What `run` executes for a plan, cheapest first."""
    out: list[tuple[str, list[str], Path]] = []
    if "repo-config" in plan.units:
        out.append(("repo config", [sys.executable, str(Path(__file__).with_name("repo_config.py"))], ROOT))
    if "ship" in plan.units:
        out.append(("ship", ["bash", "scripts/test-ship.sh"], ROOT))
    if "turn-in" in plan.units:
        out.append(("turn-in", ["uv", "run", "--no-project", "--with", "pytest==8.3.5", "pytest", "-q", "tests/turn_in"], ROOT))
    if plan.everything:
        out.append(("selector", ["uv", "run", "--no-project", "--with", "pytest==8.3.5", "pytest", "-q", "tools/test-impact"], ROOT))
    if "engine" in plan.units:
        out.append(("engine", ["uv", "run", "--no-project", "--python", "3.12", "--with", "pytest==8.3.5",
                               "--with", "pytest-xdist==3.8.0", "--with", "execnet==2.1.2", "python", "-m", "pytest",
                               "-q", "-n", "auto", "tools/implementation-loop/tests"], ROOT))
    for session in plan.sessions:
        out.append((session, ["uv", "run", "--locked", "--group", "parallel", "pytest", "-q", "-m", "not live", "-n", "auto"],
                    ROOT / session))
    if plan.suites:
        out.append((f"{len(plan.suites)} node suite(s)", ["node", "--test", *plan.suites], ROOT))
    if plan.pages:
        out.append((f"{len(plan.pages)} page(s)", ["node", "tools/html-pages/check-repo-pages.mjs", *plan.pages], ROOT))
    return out


def github_output(plan: Plan, path: str) -> None:
    shards = [1, 2] if len(plan.suites) > 1 else [1]
    every = plan.everything
    values = {
        "everything": str(plan.everything).lower(),
        "engine": str("engine" in plan.units).lower(),
        "sessions": json.dumps(plan.sessions),
        "session_tests": str(bool(plan.sessions)).lower(),
        "suites": "all" if every else " ".join(plan.suites) or "none",
        "shards": json.dumps(shards),
        "pages": "all" if every else " ".join(plan.pages) or "none",
        "html": str(bool(plan.suites or plan.pages)).lower(),
    }
    with open(path, "a", encoding="utf-8") as out:
        for key, value in values.items():
            out.write(f"{key}={value}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=["plan", "run", "github"])
    parser.add_argument("--base", default="origin/main", help="what the change is measured against (default origin/main)")
    parser.add_argument("--head", help="github: the pull request head")
    parser.add_argument("--all", action="store_true", help="select everything")
    parser.add_argument("--json", action="store_true", help="plan: print JSON")
    args = parser.parse_args(argv)

    change = pr_change(args.base, args.head) if args.action == "github" else local_change(args.base)
    plan = select(change, everything=args.all)
    if args.action == "github":
        print("\n".join(sorted(change.paths)))
        print(describe(plan))
        github_output(plan, os.environ["GITHUB_OUTPUT"])
        return 0
    if args.action == "plan":
        print(json.dumps(plan.as_dict(), indent=2) if args.json else describe(plan))
        return 0
    print(describe(plan), flush=True)
    failed = []
    for label, command, cwd in commands(plan):
        print(f"\n== {label}: {' '.join(command)}", flush=True)
        if subprocess.run(command, cwd=cwd).returncode != 0:
            failed.append(label)
    print("\n" + (f"FAILED: {', '.join(failed)}" if failed else "All selected checks passed."))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
