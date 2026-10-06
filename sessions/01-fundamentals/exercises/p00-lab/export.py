"""Export a standalone P00 lab repository, optionally with one bug planted in the model.

    python export.py --bug <name> --out <dir>
    python export.py --tests-dir --bug <name> --out <dir>

Instructor-only: this file and README.md are never copied into an export. The export holds the
student statement, the model (patched for the chosen bug), the independent checker, the
contract tests, the data and the session's pinned Python setup, committed in a fresh git repo.
Nothing written to the export names the chosen bug. With --tests-dir, the contract suite goes to
tests/test_p00_contract.py (beside an empty tests/__init__.py) and AGENTS.md names tests/; the
lab ladder's L2 done check (`git diff --stat -- tests/`) relies on that layout. Without it, the
export is unchanged.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


PACK = Path(__file__).resolve().parent
SESSION = PACK.parents[1]

# Textual patches applied to the exported p00_model.py. Each `old` must occur exactly once in
# the reference model, so a refactor of the model cannot silently turn a bug into a no-op.
BUGS = {
    "none": [],
    "flipped-sense": [
        ("highspy.ObjSense.kMinimize", "highspy.ObjSense.kMaximize"),
    ],
    "dropped-demand": [
        (
            "    for c in customer_ids:\n        h.addConstr(sum(x[p, c] for p in plant_ids) == demand[c])\n",
            "    for c in customer_ids[:-1]:\n        h.addConstr(sum(x[p, c] for p in plant_ids) == demand[c])\n",
        ),
    ],
    "relaxed-binary": [
        ("type=highspy.HighsVarType.kInteger", "type=highspy.HighsVarType.kContinuous"),
    ],
    "timelimit-as-optimal": [
        (
            'HighsModelStatus.kTimeLimit:\n        return "feasible"\n',
            'HighsModelStatus.kTimeLimit:\n        return "optimal"\n',
        ),
    ],
}

# (source, destination in the export); copied byte-for-byte.
COPIED = [
    (PACK / "p00_checker.py", "p00_checker.py"),
    (PACK / "test_p00_contract.py", "test_p00_contract.py"),
    (PACK / "data" / "plants.csv", "data/plants.csv"),
    (PACK / "data" / "customers.csv", "data/customers.csv"),
    (PACK / "data" / "costs.csv", "data/costs.csv"),
    (PACK / "PROBLEM.md", "README.md"),
    (SESSION / "pyproject.toml", "pyproject.toml"),
    (SESSION / "uv.lock", "uv.lock"),
    (SESSION / "mise.toml", "mise.toml"),
]

AGENTS_TEMPLATE = """\
# Agent instructions

This directory is the whole task. Do not read, search or edit anything outside it: no parent
directories, no other repositories, no web search for this exercise.

## Where to start

1. Read `README.md`: the problem statement and what a correct solve means.
2. Then read `p00_model.py`, the model under test.

## The contract

`p00_checker.py`, {suite} and everything in `data/` are the contract. Never edit,
weaken, skip, mark as expected to fail or special-case them, and never hard-code an expected
answer. If a test fails, the fix belongs in `p00_model.py`.

## Setup and tests

```sh
mise install && uv sync
uv run pytest
```

Without mise and uv, `python -m pytest` works in any Python 3.12 environment that has
`highspy`, `numpy` and `pytest` installed.

## Done means

Every test passes, and you can name the contract that was broken (status, feasibility,
integrality or objective) and the line in `p00_model.py` that broke it, or state that none was.
"""

AGENTS_MD = AGENTS_TEMPLATE.format(suite="`test_p00_contract.py`")
# --tests-dir: the same text, with the suite named by its folder.
AGENTS_MD_TESTS_DIR = AGENTS_TEMPLATE.format(suite="everything in `tests/`")

CLAUDE_MD = "@AGENTS.md\n"

GITIGNORE = ".venv/\n__pycache__/\n.pytest_cache/\n"

# Variables that would point git at another repository instead of the export.
GIT_REDIRECTS = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def course_checkout():
    """Return the first ancestor of this file holding `.git` (directory or worktree file)."""
    for parent in PACK.parents:
        if (parent / ".git").exists():
            return parent
    return None


def patched_model(bug):
    source = (PACK / "p00_model.py").read_text(encoding="utf-8")
    for old, new in BUGS[bug]:
        count = source.count(old)
        if count != 1:
            raise SystemExit(f"export.py: patch anchor for {bug!r} occurs {count} times, expected 1: {old!r}")
        source = source.replace(old, new)
    return source


def refuse(message):
    print(f"export.py: {message}", file=sys.stderr)
    raise SystemExit(2)


def git(out, *args):
    env = {key: value for key, value in os.environ.items() if key not in GIT_REDIRECTS}
    subprocess.run(["git", *args], cwd=out, env=env, check=True)


def write_export(out, bug, tests_dir=False):
    files = {destination: source.read_bytes() for source, destination in COPIED}
    files["p00_model.py"] = patched_model(bug).encode("utf-8")
    files["AGENTS.md"] = (AGENTS_MD_TESTS_DIR if tests_dir else AGENTS_MD).encode("utf-8")
    if tests_dir:
        files["tests/test_p00_contract.py"] = files.pop("test_p00_contract.py")
        files["tests/__init__.py"] = b""
    files["CLAUDE.md"] = CLAUDE_MD.encode("utf-8")
    files[".gitignore"] = GITIGNORE.encode("utf-8")
    for name, content in files.items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    git(out, "init", "-q", "-b", "main")
    git(out, "add", "-A")
    git(
        out,
        "-c", "user.name=P00 lab",
        "-c", "user.email=p00-lab@example.invalid",
        "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "Initial commit",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export a standalone P00 lab repository.")
    parser.add_argument("--bug", required=True, choices=sorted(BUGS), help="bug to plant ('none' for the reference)")
    parser.add_argument("--out", required=True, type=Path, help="new or empty directory outside the course repo")
    parser.add_argument("--tests-dir", action="store_true", help="put the contract suite in tests/ (lab ladder layout)")
    args = parser.parse_args(argv)

    out = args.out.expanduser().resolve()
    course = course_checkout()
    if course is not None and out.is_relative_to(course.resolve()):
        refuse(f"--out must be outside the course checkout ({course})")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        refuse(f"--out {out} exists and is not an empty directory")

    created = not out.exists()
    out.mkdir(parents=True, exist_ok=True)
    try:
        write_export(out, args.bug, args.tests_dir)
    except BaseException:
        if created:
            shutil.rmtree(out, ignore_errors=True)
        else:
            for child in out.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink()
        raise
    print(out)


if __name__ == "__main__":
    main()
