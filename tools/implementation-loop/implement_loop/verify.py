"""The trusted verifier. It runs from the engine's own checkout, never from the worktree it
judges, and it trusts nothing an implementer could have changed.

- Locked files (the acceptance checks, plus the test configuration pytest would load for
  them) are hashed when the checks are committed. Any later change, deletion, or new
  configuration file fails verification. In `pyproject.toml` only the `[tool.pytest...]`
  section is locked, so implementers can still add dependencies.
- Each command check produces an `Evidence` record bound to the exact head SHA.
- The test functions defined in the locked check files must all run; a missing test or any
  skip fails, so a check cannot be quietly emptied out.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import time
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import asdict
from pathlib import Path

from .config import TEST_CONFIG_NAMES
from .model import CheckSpec, Evidence

OUTPUT_TAIL = 3000
NO_PYTEST_CONFIG = hashlib.sha256(b"{}").hexdigest()


def digest(path: Path) -> str:
    """For pyproject.toml, the parsed `[tool.pytest]` table only, whatever its TOML spelling;
    an unparseable file is hashed whole, so any change to it is caught."""
    if path.name == "pyproject.toml":
        try:
            pytest_cfg = tomllib.loads(path.read_text(errors="replace")).get("tool", {}).get("pytest", {})
        except tomllib.TOMLDecodeError:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        return hashlib.sha256(json.dumps(pytest_cfg, sort_keys=True).encode()).hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config_candidates(root: Path, check_files: list[str], cwds: list[str]) -> list[str]:
    """Test configuration pytest could load for these checks: config files in every ancestor
    directory of a check file or check cwd, and any conftest.py under a check file's folder."""
    dirs: set[Path] = set()
    for rel in check_files + cwds:
        p = Path(rel)
        d = p if (root / p).is_dir() or rel.endswith("/") or rel in cwds else p.parent
        while True:
            dirs.add(d)
            if d == Path(".") or d == d.parent:
                break
            d = d.parent
    found: set[str] = set()
    for d in dirs:
        for name in TEST_CONFIG_NAMES:
            if (root / d / name).is_file():
                found.add(str(d / name) if d != Path(".") else name)
    for rel in check_files:
        start = root / Path(rel).parent
        if start.is_dir():
            for dirpath, dirnames, filenames in os.walk(start):
                dirnames[:] = [x for x in dirnames if x not in {".git", ".venv", "node_modules", "__pycache__"}]
                if "conftest.py" in filenames:
                    found.add(str((Path(dirpath) / "conftest.py").relative_to(root)))
    return sorted(found)


def lock(root: Path, check_files: list[str], cwds: list[str]) -> dict[str, str]:
    locked = {}
    for rel in sorted(set(check_files) | set(config_candidates(root, check_files, cwds))):
        p = root / rel
        if p.is_file():
            locked[rel] = digest(p)
    return locked


def tamper_report(root: Path, locked: dict[str, str], check_files: list[str], cwds: list[str]) -> list[str]:
    problems = []
    for rel, d in sorted(locked.items()):
        p = root / rel
        if not p.is_file():
            problems.append(f"locked file deleted: {rel}")
        elif digest(p) != d:
            problems.append(f"locked file changed: {rel}")
    for rel in config_candidates(root, check_files, cwds):
        if rel in locked:
            continue
        if Path(rel).name == "pyproject.toml" and digest(root / rel) == NO_PYTEST_CONFIG:
            continue  # a new pyproject.toml with no pytest settings cannot change how tests run
        problems.append(f"new test configuration file: {rel}")
    return problems


def expected_tests(root: Path, check_files: list[str]) -> list[str]:
    """Every test in the locked Python check files, as `path::Class::test_name` (or `path::test_name`).

    Read with Python's own parser, so two `test_contract` methods in different classes stay two
    tests. Parametrized tests count once: at least one of their cases must run."""
    found: list[str] = []

    def walk(node, rel: str, prefix: list[str]):
        for child in getattr(node, "body", []):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test"):
                found.append("::".join([rel, *prefix, child.name]))
            elif isinstance(child, ast.ClassDef):
                walk(child, rel, prefix + [child.name])

    for rel in check_files:
        p = root / rel
        if p.suffix == ".py" and p.is_file():
            try:
                walk(ast.parse(p.read_text(errors="replace")), rel, [])
            except SyntaxError:
                found.append(f"{rel}::<unparseable>")
    return sorted(set(found))


def _matches(expected: str, case: tuple[list[str], str]) -> bool:
    """Does a JUnit case (classname parts, name) correspond to an expected test id?"""
    parts = expected.split("::")
    module = Path(parts[0]).with_suffix("").parts
    want = list(module) + parts[1:-1]
    have, name = case
    if re.sub(r"\[.*\]$", "", name) != parts[-1]:
        return False
    m = min(len(want), len(have))
    return m >= len(parts) - 1 and want[-m:] == have[-m:]


def _junit_results(path: Path) -> dict[str, list]:
    """Cases from a JUnit report as (classname parts, name), grouped by outcome."""
    results: dict[str, list] = {"passed": [], "failed": [], "skipped": []}
    if not path.exists():
        return results
    for case in ET.parse(path).getroot().iter("testcase"):
        key = ((case.get("classname") or "").split("."), case.get("name", ""))
        if case.find("skipped") is not None:
            results["skipped"].append(key)
        elif case.find("failure") is not None or case.find("error") is not None:
            results["failed"].append(key)
        else:
            results["passed"].append(key)
    return results


def run_check(root: Path, spec: CheckSpec, head_sha: str, work_dir: Path, default_timeout: int = 900) -> tuple[Evidence, dict[str, list[str]] | None]:
    if spec.kind != "command" or not spec.command:
        ev = Evidence(criterion=spec.criterion, kind=spec.kind, command=None, cwd=spec.cwd, head_sha=head_sha,
                      exit_code=None, passed=False, duration_s=0.0, output_tail="", output_sha256="",
                      note="proven by an artifact review or a person, not by a command")
        return ev, None
    # Every command gets pytest's result report through the environment, so tests run from a
    # wrapper script (`bash run.sh`, `uv run pytest`, `make test`) are accounted for too.
    junit = work_dir / f"junit-{spec.criterion}-{head_sha[:12]}.xml"
    junit.unlink(missing_ok=True)
    env = dict(os.environ)
    env["PYTEST_ADDOPTS"] = (env.get("PYTEST_ADDOPTS", "") + f" -p no:cacheprovider --junitxml={junit}").strip()
    command = spec.command
    cwd = root / spec.cwd
    start = time.monotonic()
    if not cwd.is_dir():
        code, output = None, f"check directory does not exist: {spec.cwd}"
    else:
        try:
            proc = subprocess.run(["bash", "-c", command], cwd=cwd, capture_output=True, text=True,
                                  timeout=spec.timeout_s or default_timeout, env=env)
            code, output = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired as e:
            partial = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            code, output = None, f"timed out after {e.timeout}s\n{partial}"
    duration = round(time.monotonic() - start, 2)
    passed, note, tests = code == 0, "", None
    if junit.exists():
        tests = _junit_results(junit)
        if tests["skipped"]:
            passed, note = False, f"unexpected skip: {[n for _, n in tests['skipped'][:3]]}"
        elif not (tests["passed"] or tests["failed"]):
            passed, note = False, "no tests ran"
    ev = Evidence(criterion=spec.criterion, kind="command", command=spec.command, cwd=spec.cwd, head_sha=head_sha,
                  exit_code=code, passed=passed, duration_s=duration, output_tail=output[-OUTPUT_TAIL:],
                  output_sha256=hashlib.sha256(output.encode()).hexdigest(),
                  tests={k: len(v) for k, v in tests.items()} if tests else None, note=note)
    return ev, tests


def verify(root: Path, specs: list[CheckSpec], head_sha: str, work_dir: Path, locked: dict[str, str],
           check_files: list[str], expected: list[str], default_timeout: int = 900) -> tuple[bool, list[dict], list[str]]:
    """Run every command check. Returns (all passed, evidence records, problems)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    cwds = sorted({s.cwd for s in specs if s.kind == "command"})
    problems = tamper_report(root, locked, check_files, cwds)
    evidence, cases, accounted = [], [], False
    for spec in specs:
        if spec.kind != "command":
            continue
        ev, tests = run_check(root, spec, head_sha, work_dir, default_timeout)
        evidence.append(asdict(ev))
        if tests is not None:
            accounted = True
            cases += tests["passed"] + tests["failed"]
        if not ev.passed:
            problems.append(f"{spec.criterion} failed: {ev.note or f'exit {ev.exit_code}'}")
    if expected:
        if not accounted:
            problems.append("the locked tests ran without pytest result accounting; run them with pytest "
                            "so skips and missing tests can be detected")
        else:
            missing = [t for t in expected if not any(_matches(t, c) for c in cases)]
            if missing:
                problems.append(f"expected tests did not run: {missing[:5]}")
    return (not problems), evidence, problems
