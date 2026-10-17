"""The trusted verifier. It runs from the engine's own checkout, never from the worktree it
judges, and it trusts nothing an implementer could have changed.

- Locked files (the acceptance checks, plus the test configuration pytest would load for
  them) are hashed when the checks are committed. Any later change, deletion, or new
  configuration file fails verification. In `pyproject.toml` only the `[tool.pytest...]`
  section is locked, so implementers can still add dependencies.
- Each command check produces an `Evidence` record bound to the exact head SHA. Every pytest
  process the command starts, however it starts it, reports each test through the
  `loop_pytest` plugin: a failed, erroring, skipped, xfailed or xpassed test fails the check,
  and so does a pytest that ran no test or could not run (usage error, nothing collected,
  internal error, interrupted).
- The selection manifest: the test ids a passing verification ran, per criterion (`selection`),
  locked with the checks. Every later verification must run and pass each of them, so a check
  cannot be quietly emptied out. A test defined in a check file that no command selects is not
  a failure; `unselected` reports it until it gets a disposition.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import time
import tomllib
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


# ---------------------------------------------------------------------- test ids

def base_id(test_id: str) -> str:
    """A test id without its parameters: `a/test_x.py::TestA::test_b[1-x]` -> `a/test_x.py::TestA::test_b`."""
    file_part, sep, rest = test_id.partition("::")
    return file_part + sep + rest.split("[", 1)[0]


def _test_functions(root: Path, files: list[str]):
    """(id, function node) for every `test*` function or method in the Python files, and
    (`path::<unparseable>`, None) for a file Python cannot parse.

    Read with Python's own parser, so two `test_contract` methods in different classes stay two
    tests, and a test defined under `if`, `try` or `with` is still found."""

    def blocks(stmt) -> list[list]:
        """Statement lists a definition can sit in: if/else, try/except/else/finally, with, for, while, match."""
        out = [getattr(stmt, name, None) for name in ("body", "orelse", "finalbody")]
        out += [h.body for h in getattr(stmt, "handlers", [])] + [c.body for c in getattr(stmt, "cases", [])]
        return [b for b in out if isinstance(b, list)]

    def walk(statements: list, rel: str, prefix: list[str]):
        for child in statements:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if child.name.startswith("test"):
                    yield "::".join([rel, *prefix, child.name]), child
                # pytest never collects functions nested inside functions
            elif isinstance(child, ast.ClassDef):
                yield from walk(child.body, rel, prefix + [child.name])
            else:
                for block in blocks(child):
                    yield from walk(block, rel, prefix)

    for rel in files:
        p = root / rel
        if p.suffix == ".py" and p.is_file():
            try:
                tree = ast.parse(p.read_text(errors="replace"))
            except SyntaxError:
                yield f"{rel}::<unparseable>", None
                continue
            yield from walk(tree.body, rel, [])


def defined_tests(root: Path, files: list[str]) -> list[str]:
    """Every test defined in the Python files, as `path::Class::test_name` (or `path::test_name`),
    without parameters. A file that does not parse yields `path::<unparseable>`."""
    return sorted({test_id for test_id, _ in _test_functions(root, files)})


def selection(cases_by_criterion: dict) -> dict[str, list[str]]:
    """The selection manifest to lock from a passing verification: for each criterion, the ids
    of the tests that passed. A value is what `run_check` returned for the criterion's command
    (its `passed` ids), an evidence record from `verify` (its `passed_tests`), None, or a list
    of these when several commands prove one criterion. Criteria that ran no test are left out."""

    def passed(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, dict):
            ids = value.get("passed_tests", value.get("passed"))
            return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []
        return [i for v in value for i in passed(v)]

    out = {criterion: sorted(set(passed(value))) for criterion, value in cases_by_criterion.items()}
    return {criterion: ids for criterion, ids in sorted(out.items()) if ids}


def unselected(root: Path, check_files: list[str], manifest: dict[str, list[str]] | None,
               dispositions: dict[str, str] | None) -> list[str]:
    """Tests defined in the check files that no manifest entry selected (compared without
    parameters) and that have no disposition ("owner-run", or "excluded: <reason>")."""
    selected = {base_id(i) for ids in (manifest or {}).values() for i in ids}
    disposed = {base_id(i) for i in (dispositions or {})}
    return [t for t in defined_tests(root, check_files) if t not in selected and t not in disposed]


def not_run(manifest: dict[str, list[str]] | None, ran: list[str] | set[str]) -> list[str]:
    """Manifest ids that did not run and pass. A parametrized id must match exactly; an id
    recorded without parameters is satisfied by any of its parametrized cases."""
    ran = set(ran)
    ran_bases = {base_id(i) for i in ran}
    wanted = sorted({i for ids in (manifest or {}).values() for i in ids})
    return [i for i in wanted if i not in ran and not (base_id(i) == i and i in ran_bases)]


# ------------------------------------------------------- tests that can never pass

_FAILING_RAISES = {"AssertionError", "Exception", "NotImplementedError"}
_JS_SUFFIXES = {".js", ".mjs", ".cjs", ".ts", ".mts", ".cts"}
_JS_TEST = re.compile(
    r"""(?<![\w$.])(?:test|it)(?:\.only)?\s*\(\s*"""
    r"""(?P<q>['"`])(?:\\.|(?!(?P=q)).)*(?P=q)\s*,\s*"""                  # the test name
    r"""(?:(?P<options>\{[^{}]*\})\s*,\s*)?"""                              # node:test options
    r"""(?:async\s+)?(?:function\b\s*\*?\s*[\w$]*\s*\([^)]*\)|\([^)]*\)|[\w$]+)\s*(?:=>\s*)?\{""",
    re.S)
_JS_LEADING = re.compile(r"(?:\s+|//[^\n]*|/\*.*?\*/)*", re.S)
_JS_FAILS = re.compile(r"assert\.fail\s*\(|throw\s+(?:new\s+)?Error\s*\(|assert(?:\.ok)?\s*\(\s*false\s*[,)]")
_SHELL_NOISE = re.compile(r"(?:set\s|echo\b|printf\b|:(?:\s|$))")
_SHELL_FAILS = re.compile(r"(?:exit\s+[1-9]\d*|(?:/usr)?(?:/bin/)?false)")


def _python_always_fails(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Assert):
        return isinstance(stmt.test, ast.Constant) and not stmt.test.value
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        func = stmt.value.func   # pytest.fail(...), self.fail(...)
        return (isinstance(func, ast.Attribute) and func.attr == "fail" and isinstance(func.value, ast.Name)
                and func.value.id in {"pytest", "self"})
    if isinstance(stmt, ast.Raise) and stmt.exc is not None:
        exc = stmt.exc.func if isinstance(stmt.exc, ast.Call) else stmt.exc
        return isinstance(exc, ast.Name) and exc.id in _FAILING_RAISES
    return False


def _in_js_comment(text: str, pos: int) -> bool:
    line = text[text.rfind("\n", 0, pos) + 1:pos]
    return "//" in line or text.rfind("/*", 0, pos) > text.rfind("*/", 0, pos)


def unconditional_failures(root: Path, files: list[str]) -> list[str]:
    """Tests in these files that fail whatever the code under test does, so no implementation
    can make them pass: a Python test whose first statement is `assert False` (or another
    falsy constant), `pytest.fail(...)`, `self.fail(...)` or `raise AssertionError/Exception/
    NotImplementedError`; a JavaScript or TypeScript `test(...)`/`it(...)` whose callback starts
    with `assert.fail(...)`, `throw new Error(...)` or `assert.ok(false)`; a shell script whose
    only command is `exit 1` (any non-zero status) or `false`. Deliberately narrow: anything
    that depends on the code under test is left alone."""
    problems: list[str] = []
    for test_id, node in _test_functions(root, files):
        if node is None:
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            body = body[1:]   # the docstring
        if body and _python_always_fails(body[0]):
            problems.append(f"{test_id} always fails: its first statement is `{ast.unparse(body[0])[:80]}`")
    for rel in files:
        p = root / rel
        if not p.is_file():
            continue
        text = p.read_text(errors="replace")
        if p.suffix in _JS_SUFFIXES:
            for m in _JS_TEST.finditer(text):
                if _in_js_comment(text, m.start()) or re.search(r"\b(?:skip|todo)\b", m.group("options") or ""):
                    continue
                start = _JS_LEADING.match(text, m.end()).end()
                first = _JS_FAILS.match(text, start)
                if first:
                    line = text.count("\n", 0, m.start()) + 1
                    problems.append(f"{rel}:{line}: the test always fails: its callback starts with `{first.group(0).strip()}`")
        elif p.suffix in {".sh", ".bash"} or (p.suffix != ".py" and re.match(r"#!.*\b(?:ba|da|z)?sh\b", text)):
            commands = []
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                commands += [c.strip() for c in line.split(";") if c.strip()]
            effective = [c for c in commands if not _SHELL_NOISE.match(c)]
            if len(effective) == 1 and _SHELL_FAILS.fullmatch(re.sub(r"\s+#.*$", "", effective[0])):
                problems.append(f"{rel}: the script always fails: its only command is `{effective[0]}`")
    return problems


# ------------------------------------------------------------------ running checks

PLUGIN = "implement_loop.loop_pytest"
ENGINE_DIR = Path(__file__).resolve().parent.parent   # what PYTHONPATH needs for PLUGIN
# outcome -> what it means for a check; a worse outcome of the same test wins (as in loop_pytest)
OUTCOMES = {"passed": "passed", "xfailed": "skipped", "skipped": "skipped", "xpassed": "failed",
            "failed": "failed", "error": "failed"}
SEVERITY = {"passed": 0, "xfailed": 1, "skipped": 2, "xpassed": 3, "failed": 4, "error": 5}
# pytest exit statuses that mean it did not run the tests it was given (0 and 1 are results)
BAD_EXIT = {2: "interrupted", 3: "internal error", 4: "usage error", 5: "no tests collected"}


def _run(command: str, cwd: Path, timeout: int, env: dict[str, str]) -> tuple[int | None, str, bool]:
    """(exit code, output, timed out). The command runs in its own process group, so a timeout
    stops everything it started, not only bash: `pytest A && pytest B` would otherwise keep
    the output pipes open until B finished."""
    proc = subprocess.Popen(["bash", "-c", command], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace", env=env, start_new_session=True)

    def kill():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, (out or "") + (err or ""), False
    except subprocess.TimeoutExpired:
        kill()
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:   # something left the group and holds the pipes
            out, err = "", ""
        return None, f"timed out after {timeout} s\n{out or ''}{err or ''}", True
    except BaseException:
        kill()
        proc.wait()
        raise


def _read_records(report_dir: Path) -> dict | None:
    """Every pytest process's record, merged: ids by outcome, what was collected, how many
    processes ran, and the exit statuses that are not results. None when no pytest ran."""
    records = sorted(report_dir.glob("run-*.json"))
    if not records:
        return None
    worst: dict[str, str] = {}
    collected: dict[str, None] = {}
    bad_exit: list[int | None] = []
    for path in records:
        try:
            data = json.loads(path.read_text())
            status = data["exitstatus"]
            cases = [(str(c["id"]), c["outcome"] if c["outcome"] in SEVERITY else "error") for c in data["cases"]]
            selected = [str(i) for i in data.get("collected") or []]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            bad_exit.append(None)   # unreadable: no evidence either way
            continue
        if status not in (0, 1):
            bad_exit.append(status)
        for test_id, outcome in cases:
            if test_id not in worst or SEVERITY[outcome] > SEVERITY[worst[test_id]]:
                worst[test_id] = outcome
        collected.update(dict.fromkeys(selected))
    out: dict = {"passed": [], "failed": [], "skipped": []}
    for test_id, outcome in sorted(worst.items()):
        out[OUTCOMES[outcome]].append(test_id)
    out.update(collected=list(collected), processes=len(records), bad_exit=bad_exit)
    return out


def _pytest_said(output: str, status: int | None) -> str:
    """pytest's own one-line account of why it stopped, if it printed one."""
    if status == 3:
        lines = re.findall(r"^INTERNALERROR> (.+)$", output, re.M)
        return lines[-1].strip()[:200] if lines else ""
    for pattern in (r"^\S+: error: (.+)$", r"^ERROR: (.+)$", r"^Interrupted: (.+)$"):
        m = re.search(pattern, output, re.M)
        if m:
            return m.group(1).strip()[:200]
    return ""


def _notes(cases: dict | None, output: str) -> list[str]:
    """Why the pytest runs of a command do not prove anything, in words."""
    if cases is None:
        if f'Error importing plugin "{PLUGIN}"' in output:
            return ["pytest could not load the verifier's result plugin; if the command sets PYTHONPATH, "
                    "extend it (PYTHONPATH=src:$PYTHONPATH) instead of replacing it"]
        return []
    notes = []
    if cases["failed"]:
        notes.append(f"failed tests: {cases['failed'][:5]}")
    if cases["skipped"]:
        notes.append(f"unexpected skip: {cases['skipped'][:5]}")
    nothing_ran = not (cases["passed"] or cases["failed"] or cases["skipped"])
    stopped = []
    for status in dict.fromkeys(cases["bad_exit"]):
        said = _pytest_said(output, status)
        if status is None:
            stopped.append("pytest stopped before running any test" + (f" ({said})" if said else ""))
        elif not (status == 5 and nothing_ran):   # nothing collected anywhere: "no tests ran" says it
            label = BAD_EXIT.get(status, "not a test result")
            stopped.append(f"pytest exited {status} ({label}{': ' + said if said else ''})")
    if nothing_ran and not stopped:
        notes.append("no tests ran")
    return notes + stopped


def run_check(root: Path, spec: CheckSpec, head_sha: str, work_dir: Path, default_timeout: int = 900,
              extra_env: dict[str, str] | None = None) -> tuple[Evidence, dict | None]:
    """Run one check command. Returns its evidence, and what its pytest processes reported:
    `{"passed", "failed", "skipped", "collected": [ids], "processes": n, "bad_exit": [status]}`
    (failed includes errors and xpasses, skipped includes xfails), or None when no pytest ran.

    The command passes when it exits 0, no test failed, erred, xpassed, xfailed or was skipped,
    and, if pytest ran at all, at least one test ran and every pytest ended with a test result
    (not interrupted, internal error, usage error or nothing collected)."""
    if spec.kind != "command" or not spec.command:
        ev = Evidence(criterion=spec.criterion, kind=spec.kind, command=None, cwd=spec.cwd, head_sha=head_sha,
                      exit_code=None, passed=False, duration_s=0.0, output_tail="", output_sha256="",
                      note="proven by an artifact review or a person, not by a command")
        return ev, None
    # A fresh record directory per check, and the plugin in every pytest the command starts,
    # through the environment: tests run from a wrapper (`bash run.sh`, `uv run pytest`,
    # `make test`) or several pytest runs chained in one command are all accounted for.
    report_dir = (work_dir / f"pytest-{re.sub(r'[^A-Za-z0-9._-]', '_', spec.criterion)}-{head_sha[:12]}").resolve()
    shutil.rmtree(report_dir, ignore_errors=True)
    report_dir.mkdir(parents=True)
    env = dict(os.environ) | dict(extra_env or {})
    env.pop("LOOP_PYTEST_PID", None)   # a verification is never nested in an outer one's pytest
    env["LOOP_REPORT_DIR"] = str(report_dir)
    env["LOOP_REPO_ROOT"] = str(Path(root).resolve())
    env["PYTEST_ADDOPTS"] = (env.get("PYTEST_ADDOPTS", "") + f" -p {PLUGIN} -p no:cacheprovider").strip()
    env["PYTHONPATH"] = os.pathsep.join([str(ENGINE_DIR)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    cwd = root / spec.cwd
    timeout = spec.timeout_s or default_timeout
    start = time.monotonic()
    notes: list[str] = []
    if not cwd.is_dir():
        code, output = None, f"check directory does not exist: {spec.cwd}"
        notes.append(output)
    else:
        code, output, timed_out = _run(spec.command, cwd, timeout, env)
        if timed_out:
            notes.append(f"timed out after {timeout} s")
    duration = round(time.monotonic() - start, 2)
    cases = _read_records(report_dir)
    notes += _notes(cases, output)
    ev = Evidence(criterion=spec.criterion, kind="command", command=spec.command, cwd=spec.cwd, head_sha=head_sha,
                  exit_code=code, passed=code == 0 and not notes, duration_s=duration,
                  output_tail=output[-OUTPUT_TAIL:], output_sha256=hashlib.sha256(output.encode()).hexdigest(),
                  tests={k: len(cases[k]) for k in ("passed", "failed", "skipped")} if cases else None,
                  note="; ".join(notes))
    return ev, cases


def verify(root: Path, specs: list[CheckSpec], head_sha: str, work_dir: Path, locked: dict[str, str],
           check_files: list[str], manifest: dict[str, list[str]] | None, default_timeout: int = 900,
           extra_env: dict[str, str] | None = None,
           check_tamper: bool = True) -> tuple[bool, list[dict], list[str], list[str]]:
    """Run every command check. Returns (all passed, evidence records, problems, ids of the
    tests that passed).

    With a selection `manifest` (criterion -> test ids, from `selection`), each of its tests
    must run and pass in this verification; tests that run without being in it are fine. With
    None, only each command's own result counts. Each evidence record also carries the ids its
    command passed (`passed_tests`), what `selection` needs to lock a manifest.
    `extra_env` reaches the check commands only (for example the browser's private libraries);
    `check_tamper=False` re-runs another issue's checks for regressions, behaviour only."""
    work_dir.mkdir(parents=True, exist_ok=True)
    cwds = sorted({s.cwd for s in specs if s.kind == "command"})
    problems = tamper_report(root, locked, check_files, cwds) if check_tamper else []
    evidence: list[dict] = []
    ran: set[str] = set()
    accounted = False
    for spec in specs:
        if spec.kind != "command":
            continue
        ev, cases = run_check(root, spec, head_sha, work_dir, default_timeout, extra_env)
        evidence.append(asdict(ev) | {"passed_tests": list(cases["passed"]) if cases else []})
        if cases is not None:
            accounted = True
            ran.update(cases["passed"])
        if not ev.passed:
            problems.append(f"{spec.criterion} failed: {ev.note or f'exit {ev.exit_code}'}")
    missing = not_run(manifest, ran)
    if missing:
        more = f" and {len(missing) - 5} more" if len(missing) > 5 else ""
        why = "" if accounted else ("; no check command ran pytest, so no test result was recorded: run "
                                    "the tests with pytest so skips and missing tests can be detected")
        problems.append(f"locked tests did not run: {missing[:5]}{more}{why}")
    return (not problems), evidence, problems, sorted(ran)
