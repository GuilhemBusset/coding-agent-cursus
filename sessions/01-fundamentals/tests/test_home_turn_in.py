"""The homework sheet end to end, offline: notes, a feasible P01 plan, then the real turn-in.

A student without push access (a clone of the course, or a clone of their fork) fills
exercises/home-notes.md, puts a checker-feasible solution.json in place and runs
`bash scripts/turn-in.sh 01`, what /turn-in 01 and $turn-in 01 run. Git, the hooks, the
session's turn-in-check.sh and the P01 checker are real; only gh is faked, with real jq
reading its --jq queries. GitHub URLs are rewritten to local bare repos and
GIT_ALLOW_PROTOCOL=file keeps the network out. The live run from a non-owner account is
the owner's.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from test_p01_homework import CONTRACTS, PACK, checker, read_instance, single_leg_candidate


SESSION = Path(__file__).resolve().parents[1]
ROOT = SESSION.parents[1]
EXERCISES = "sessions/01-fundamentals/exercises"
HANDLE, COURSE, FORK = "stud", "course/cursus", "stud/cursus"

FAKE_GH = r'''#!/usr/bin/env bash
set -euo pipefail
query=''; fields=''; pos=()
while (($#)); do
  case "$1" in
    --jq) query=$2; shift 2 ;;
    --json) fields=$2; shift 2 ;;
    --paginate|--clone=false) shift ;;
    *) pos+=("$1"); shift ;;
  esac
done
emit() { if [[ -n "$query" ]]; then jq -r "$query"; else cat; fi; }
case "${pos[0]} ${pos[1]}" in
  'api user') jq -n --arg l "$GH_LOGIN" '{login:$l}' | emit ;;
  'repo view') jq --arg r "${pos[2]}" '.[$r]' "$GH_REPOS" | emit ;;
  'repo fork') ;;
  "api repos/$GH_COURSE/forks") jq -n --arg f "$GH_FORK" --arg l "$GH_LOGIN" '[{owner:{login:$l},full_name:$f}]' | emit ;;
  *) echo "unexpected gh call: ${pos[*]}" >&2; exit 91 ;;
esac
'''


def git(*args, cwd, env):
    result = subprocess.run(["git", *map(str, args)], cwd=cwd, env=env, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return result.stdout.strip()


def sandbox(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "GH_", "GITHUB_"))}
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "gh").write_text(FAKE_GH, encoding="utf-8")
    (bindir / "gh").chmod(0o755)
    repos = {
        COURSE: {"nameWithOwner": COURSE, "parent": None, "viewerPermission": "READ",
                 "defaultBranchRef": {"name": "main"}},
        FORK: {"nameWithOwner": FORK, "parent": {"nameWithOwner": COURSE}, "viewerPermission": "ADMIN",
               "defaultBranchRef": {"name": "main"}},
    }
    (tmp_path / "repos.json").write_text(json.dumps(repos), encoding="utf-8")
    env.update({
        "PATH": f"{bindir}{os.pathsep}{env['PATH']}", "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "file",
        "GIT_AUTHOR_NAME": "Student", "GIT_AUTHOR_EMAIL": "student@example.invalid",
        "GIT_COMMITTER_NAME": "Student", "GIT_COMMITTER_EMAIL": "student@example.invalid",
        "GH_LOGIN": HANDLE, "GH_REPOS": str(tmp_path / "repos.json"), "GH_COURSE": COURSE, "GH_FORK": FORK,
    })
    # The course as students clone it: the turn-in script, the hooks and Session 1's exercises.
    seed = tmp_path / "seed"
    tracked = git("ls-files", "-z", "scripts/turn-in.sh", ".githooks", EXERCISES, cwd=ROOT, env=env)
    for name in filter(None, tracked.split("\0")):
        (seed / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, seed / name)
    git("init", "-q", "-b", "main", cwd=seed, env=env)
    git("add", ".", cwd=seed, env=env)
    git("commit", "-q", "-m", "Course", cwd=seed, env=env)
    bares = {}
    for name in (COURSE, FORK):
        bares[name] = tmp_path / (name.replace("/", "-") + ".git")
        git("clone", "-q", "--bare", seed, bares[name], cwd=tmp_path, env=env)
        git("config", "--global", "--add", f"url.{bares[name]}.insteadOf", f"https://github.com/{name}.git", cwd=tmp_path, env=env)
    return env, bares


@pytest.mark.parametrize("origin", [COURSE, FORK], ids=["non-owner-clone", "fork-clone"])
def test_sheet_end_to_end_turns_in_from_a_fork(tmp_path, origin):
    env, bares = sandbox(tmp_path)
    clone = tmp_path / "student"
    git("clone", "-q", f"https://github.com/{origin}.git", clone, cwd=tmp_path, env=env)
    git("config", "core.hooksPath", ".githooks", cwd=clone, env=env)
    work = clone / EXERCISES

    # Part 3: a plan the checker proves feasible (only optimality may fail), then its verdict.
    plan = single_leg_candidate(read_instance(PACK), True)
    (work / "homework-p01/solution.json").write_text(json.dumps(plan), encoding="utf-8")
    verdict = checker(work / "homework-p01").stdout.splitlines()
    failures = [line for line in verdict if line.split(":", 1)[0] in CONTRACTS]
    assert [line.split(":", 1)[0] for line in failures] == ["optimality"], verdict
    # Parts 1 to 3 go into the notes, in the sheet's template.
    (work / "home-notes.md").write_text(
        f"# Session 1 homework · {HANDLE}\n\n## Part 1 · Two demos, rerun\n- Sampling: 3 of 5 distinct, against 5 of 5 in class.\n"
        "- Strawberry: 1 of 5 right; tokens, not letters.\n\n## Part 2 · Sampling, not retrieval\n"
        "The reply is drawn token by token. Nothing is looked up. So I check it with the checker.\n\n"
        "## Part 3 · P01\n- Checker verdict: " + "\n".join(verdict[:1] + failures) + "\n", encoding="utf-8")

    # Part 4: the turn-in, run from the repository root as the sheet says.
    result = subprocess.run(["bash", "scripts/turn-in.sh", "01"], cwd=clone, env=env, text=True,
                            capture_output=True, timeout=300)
    log = result.stdout + result.stderr
    assert result.returncode == 0, log
    assert "Running sessions/01-fundamentals/exercises/turn-in-check.sh" in log
    assert all(line in log for line in failures), log  # the verdict in the notes is the one printed
    branch = f"homework/s01/{HANDLE}"
    assert f"https://github.com/{FORK}/tree/{branch}" in result.stdout
    assert f"Compare with the course: https://github.com/{COURSE}/compare/main...{HANDLE}:{branch}" in result.stdout

    fork, course = bares[FORK], bares[COURSE]
    assert not git("ls-remote", course, f"refs/heads/{branch}", cwd=tmp_path, env=env)
    assert git("log", "-1", "--format=%s", branch, cwd=fork, env=env) == f"Turn in session 01 homework ({HANDLE})"
    changed = git("diff", "--name-only", "main", branch, cwd=fork, env=env).splitlines()
    assert sorted(changed) == [f"{EXERCISES}/home-notes.md", f"{EXERCISES}/homework-p01/solution.json"]
