"""Issue 25 acceptance contracts, authored before implementation (ADR 0011).

Run from the session with ``uv run pytest -q tests/test_cold_open.py``.
Review remains required: teaching prose, the formulation and solver-derived
values in each model, authentic CLI/tool transcripts, redactions, and the
disposable-clone rehearsal procedure cannot be certified by text matching.
Missing runs fail; neither a timing-table assertion nor a harness solve replaces
the agent's own successful tool call.

Evidence interface: the specified === sections === contain plain key: value
metadata/timing records (key=value also accepted). Metadata keys are cli, run,
version, model, date, commit, prompt sha256, problem sha256, model sha256.
Timing keys are start, end, exit. The rehearsal Markdown table needs CLI, Run,
Version, Model, Date, Minutes, Exit; optional Start/End must match. Common column
aliases are accepted. Runbook commands may be in fenced blocks or inline code;
shell continuation lines are joined. Transcript agent output may be rendered
text or JSONL; JSON strings are decoded before looking for tool certificates.

The independent LP oracle checks feasibility and weak/strong duality, not an
answer string. Negative oracle cases, a failed-solver injection, and dirty reset
scenarios exercise more than the obvious happy-path certificate. All commands
are offline; git mutations occur only in disposable test repositories.
"""

import ast
from datetime import date, datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from urllib.parse import unquote

import pytest


SESSION = Path(__file__).resolve().parents[1]
RELATIVE = Path("sessions/01-fundamentals/cursus/demos/cold-open")
DEMO = SESSION / "cursus/demos/cold-open"
RUNS = [(cli, number) for cli in ("claude", "codex") for number in (1, 2)]
C = (40, 30)
A = ((1, 1), (2, 1), (1, 3))
B = (40, 60, 90)
ROWS = ("assembly", "carpentry", "finishing")
COLS = ("tables", "chairs")
TOL = 1e-6
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
RESET = ('git -C "$(git rev-parse --show-toplevel)" restore --source=HEAD '
         '--staged --worktree -- sessions/01-fundamentals/cursus/demos/cold-open '
         '&& git -C "$(git rev-parse --show-toplevel)" clean -fdx -- '
         'sessions/01-fundamentals/cursus/demos/cold-open')
SECTIONS = ("meta", "reset", "clean-state", "invocation", "agent", "harness-check", "timing")
COMMERCIAL = {"gurobipy", "gurobi", "cplex", "docplex", "xpress", "mosek", "coptpy", "localsolver"}
NETWORK = {"socket", "urllib", "http", "ssl", "requests", "httpx", "aiohttp", "ftplib",
           "smtplib", "telnetlib", "xmlrpc", "webbrowser"}
ALIASES = {
    "cli": {"cli", "agent", "harness"},
    "run": {"run", "runnumber", "runno", "repetition"},
    "version": {"version", "cliversion", "agentversion"},
    "model": {"model", "modelid", "modelname"},
    "date": {"date", "rundate"},
    "minutes": {"minutes", "elapsedminutes", "elapsedmin", "durationminutes", "durationmin"},
    "exit": {"exit", "exitcode", "doneexit", "doneexitcode"},
    "start": {"start", "started", "startutc", "starttimestamp", "startedat"},
    "end": {"end", "ended", "endutc", "endtimestamp", "endedat"},
    "commit": {"commit", "revision", "commitsha", "baselinecommit"},
    "promptsha256": {"promptsha256", "prompttxtsha256"},
    "problemsha256": {"problemsha256", "problemmdsha256"},
    "modelsha256": {"modelsha256", "modelpysha256"},
}


def read(path):
    assert path.is_file(), f"Missing required artifact: {path}"
    source = path.read_text(encoding="utf-8")
    assert source.strip(), f"Empty artifact: {path}"
    return source


def normalized(value):
    return re.sub(r"[^a-z0-9]", "", value.lower())


def key(value):
    value = normalized(value)
    return next((name for name, aliases in ALIASES.items() if value in aliases), value)


def cli_name(value):
    value = normalized(value)
    return {"claudecode": "claude", "codexcli": "codex"}.get(value, value)


def run_number(value):
    match = re.fullmatch(r"(?:run\s*)?([12])", value.strip(), re.I)
    assert match, f"Expected measured run 1 or 2: {value}"
    return int(match[1])


def child_env():
    env = os.environ.copy()
    for name in list(env):
        if name.startswith("GIT_") or name in {"PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"}:
            env.pop(name)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", UV_OFFLINE="1")
    return env


def run(args, cwd):
    return subprocess.run([str(arg) for arg in args], cwd=cwd, env=child_env(),
                          capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)


def success(args, cwd):
    result = run(args, cwd)
    assert result.returncode == 0, f"{args}\n{result.stdout}\n{result.stderr}"
    return result.stdout


def model_path(cli, number):
    return DEMO / "recorded" / f"{cli}_run{number}_model.py"


def transcript(cli, number):
    source = read(DEMO / "recorded" / f"{cli}-run{number}.txt")
    matches = list(re.finditer(r"^===\s*([\w-]+)\s*===\s*$", source, re.M))
    assert [match[1] for match in matches] == list(SECTIONS), "Need the seven ordered evidence sections"
    return {match[1]: source[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(source)].strip()
            for i, match in enumerate(matches)}


def fields(source):
    result = {}
    for line in source.splitlines():
        match = re.fullmatch(r"\s*([^:=]+?)\s*[:=]\s*(.*?)\s*", line)
        assert match, f"Expected evidence key: value, got {line!r}"
        name = key(match[1])
        assert name not in result, f"Duplicate evidence field: {name}"
        result[name] = match[2].strip("`")
    return result


def metadata(parts, cli, number):
    meta = fields(parts["meta"])
    required = {"cli", "run", "version", "model", "date", "commit", "promptsha256", "problemsha256", "modelsha256"}
    assert required <= meta.keys(), f"Missing metadata: {required - meta.keys()}"
    assert cli_name(meta["cli"]) == cli and run_number(meta["run"]) == number
    assert re.search(r"\d+\.\d+(?:\.\d+)?", meta["version"]), "Record the actual CLI version"
    assert meta["model"] and normalized(meta["model"]) not in {"unknown", "na", "notmeasured", "default"}
    date.fromisoformat(meta["date"])
    assert re.fullmatch(r"[0-9a-f]{7,64}", meta["commit"]), "Record the rehearsal baseline commit"
    for name in ("promptsha256", "problemsha256", "modelsha256"):
        assert re.fullmatch(r"[0-9a-f]{64}", meta[name]), f"Missing SHA256: {name}"
    return meta


def rehearsal_rows():
    required = {"cli", "run", "version", "model", "date", "minutes", "exit"}
    rows, columns = {}, None
    for line in read(DEMO / "rehearsal.md").splitlines():
        if not line.lstrip().startswith("|"):
            columns = None
            continue
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        header = [key(cell) for cell in cells]
        if required <= set(header):
            columns = header
        elif columns is not None:
            assert len(cells) == len(columns), "Malformed rehearsal timing row"
            row = dict(zip(columns, cells))
            identity = (cli_name(row["cli"]), run_number(row["run"]))
            assert identity not in rows, f"Duplicate run: {identity}"
            rows[identity] = row
    assert set(rows) == set(RUNS), "Need two measured runs of each CLI"
    return rows


def rendered(source):
    """Decode JSONL tool output as well as already-rendered transcripts."""
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    lines = []
    for line in source.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            lines.append(line)
        else:
            lines.extend(strings(value))
    return "\n".join(lines)


def certificate(source):
    patterns = [r"status:\s*(optimal|kOptimal)",
                rf"solution:\s*tables\s*=\s*({NUMBER})\s*,\s*chairs\s*=\s*({NUMBER})",
                rf"duals:\s*assembly\s*=\s*({NUMBER})\s*,\s*carpentry\s*=\s*({NUMBER})\s*,\s*finishing\s*=\s*({NUMBER})",
                rf"primal objective:\s*({NUMBER})", rf"dual objective:\s*({NUMBER})",
                rf"duality gap:\s*({NUMBER})", r"binding constraints:\s*([^\n]+)"]
    # Every line is anchored; quoted source code does not count as executed output.
    pattern = r"[ \t]*" + r"[ \t]*\n[ \t]*".join(patterns) + r"[ \t]*$"
    matches = list(re.finditer("^" + pattern, rendered(source), re.M | re.I))
    assert matches, "Missing seven-line optimal certificate in executed output"
    values = matches[-1].groups()
    numbers = tuple(float(value) for value in values[1:9])
    assert all(math.isfinite(value) for value in numbers)
    names = [item.lower() for item in re.split(r"[,;\s]+", values[9].strip())]
    assert len(names) == len(set(names)) and set(names) <= set(ROWS), "Invalid binding row identifiers"
    return numbers, frozenset(names)


def validate(cert):
    values, binding = cert
    x, y = values[:2], values[2:5]
    primal, dual, gap = values[5:]
    assert all(value >= -TOL for value in (*x, *y)), "Nonnegativity"
    slack = [bound - sum(a * v for a, v in zip(row, x)) for row, bound in zip(A, B)]
    reduced = [sum(A[i][j] * y[i] for i in range(3)) - C[j] for j in range(2)]
    assert all(value >= -TOL for value in slack), "Primal feasibility"
    assert all(value >= -TOL for value in reduced), "Dual feasibility"
    assert abs(primal - sum(c * v for c, v in zip(C, x))) <= TOL, "Primal objective"
    assert abs(dual - sum(b * v for b, v in zip(B, y))) <= TOL, "Dual objective"
    assert 0 <= gap <= TOL and abs(gap - abs(primal - dual)) <= TOL, "Duality gap"
    assert binding == {name for name, value in zip(ROWS, slack) if abs(value) <= TOL}, "Binding rows"
    assert all(abs(s * v) <= TOL for s, v in zip(slack, y)), "Row complementary slackness"
    assert all(abs(s * v) <= TOL for s, v in zip(reduced, x)), "Column complementary slackness"


def agent_certificate(parts):
    source = rendered(parts["agent"])
    command = re.search(r"\buv\s+run\s+python\s+(?:\./)?work/model\.py\b", source)
    assert command, "Agent must itself execute uv run python work/model.py"
    assert re.search(r"\b(?:Bash|exec|exec_command|shell|tool_use|tool call|command_execution)\b",
                     source[:command.end()], re.I), "Need a recorded tool call, not just assistant prose"
    result = certificate(source[command.end():])
    validate(result)
    return result


def assert_same(left, right):
    assert left[0] == pytest.approx(right[0], rel=0, abs=TOL)
    assert left[1] == right[1]


def imports(tree):
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "Recorded model must be standalone"
            roots.add((node.module or "").split(".")[0])
    return roots


def model_tree(cli, number):
    path = model_path(cli, number)
    return ast.parse(read(path), filename=str(path))


def relative_links():
    source = read(DEMO / "README.md")
    targets = re.findall(r"\[[^\]]*\]\(<?([^\s)>]+)>?(?:\s+\"[^\"]*\")?\)", source)
    targets += re.findall(r"^\s*\[[^\]]+\]:\s*<?([^\s>]+)>?", source, re.M)
    found = set()
    for target in targets:
        target = unquote(target.split("#")[0])
        if not target or re.match(r"[a-zA-Z][\w+.-]*:", target):
            continue
        path = (DEMO / target).resolve()
        assert not target.startswith("/") and path.is_relative_to(SESSION), target
        assert path.exists(), f"Broken runbook link: {target}"
        found.add(path)
    required = {DEMO / name for name in ("problem.md", "prompt.txt", "rehearsal.md")}
    required.update(model_path(*identity) for identity in RUNS)
    required.update(DEMO / "recorded" / f"{cli}-run{number}.txt" for cli, number in RUNS)
    assert required <= found, f"Runbook must link all artifacts: {required - found}"


def reset_line():
    source = read(DEMO / "README.md")
    section = re.search(r"^## Reset\s*\n(.*?)(?=^## |\Z)", source, re.M | re.S)
    assert section, "Missing ## Reset"
    blocks = re.findall(r"^```[^\n]*\n(.*?)^```\s*$", section[1], re.M | re.S)
    assert len(blocks) == 1 and blocks[0].strip() == RESET, "One path-anchored reset line is required"
    return blocks[0].strip()


def runbook_command(cli):
    source = read(DEMO / "README.md").replace("\\\n", " ")
    code = re.findall(r"^```[^\n]*\n(.*?)^```", source, re.M | re.S)
    code += re.findall(r"(?<!`)`([^`\n]+)`(?!`)", source)
    candidates = set()
    for block in code:
        for line in block.splitlines():
            line = line.strip()
            if re.search(rf"\b{cli}\s+{'-p' if cli == 'claude' else 'exec'}\b", line):
                if '"$(cat prompt.txt)"' in line:
                    candidates.add(line)
    assert len(candidates) == 1, f"Need one unambiguous primary {cli} command in the runbook"
    command = candidates.pop()
    assert ('--permission-mode acceptEdits' in command and '--allowedTools "Bash(uv run:*)"' in command
            if cli == "claude" else '--sandbox workspace-write' in command)
    return command


@pytest.fixture(scope="module")
def model_outputs():
    # A network-denying audit hook also covers indirect network attempts. No CLI
    # or uv process is involved: use the already provisioned session interpreter.
    runner = """
import sys
from pathlib import Path
def offline(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname'}:
        raise RuntimeError('network forbidden in recorded fallback')
sys.addaudithook(offline)
path = Path(sys.argv[1])
exec(compile(path.read_bytes(), str(path), 'exec'), {'__name__': '__main__', '__file__': str(path)})
"""
    result = {}
    for identity in RUNS:
        path = model_path(*identity)
        read(path)
        output = success([sys.executable, "-c", runner, path], DEMO)
        result[identity] = certificate(output)
        validate(result[identity])
    return result


def test_d1_artifacts_links_and_unspoiled_prompt():
    for name in ("README.md", "problem.md", "prompt.txt"):
        read(DEMO / name)
    relative_links()
    prompt = read(DEMO / "prompt.txt")
    assert not re.search(r"\b1[,_ ]?400(?:\.0+)?\b", prompt), "Prompt leaks optimum"
    for name, value in zip(ROWS, (20, 10, 0)):
        assert not re.search(rf"\b{name}\s*[:=]\s*{value}(?:\.0+)?\b", prompt, re.I), "Prompt leaks duals"
    assert not re.search(r"\b20(?:\.0+)?\s*[,;]\s*10(?:\.0+)?\s*[,;]\s*0(?:\.0+)?\b", prompt), "Prompt leaks dual vector"


def test_d2_problem_coefficients():
    source = read(DEMO / "problem.md").lower()
    for value in set(C) | set(B) | {value for row in A for value in row}:
        word = {1: "one", 2: "two", 3: "three"}.get(value)
        assert re.search(rf"(?<![\d.]){value}(?:\.0+)?(?![\d.])", source) or (word and re.search(rf"\b{word}\b", source)), (
            f"Problem must state coefficient {value}; placement and units require prose review")


@pytest.mark.parametrize("cli,number", RUNS)
def test_d2_recorded_model_and_agent_certificate(cli, number, model_outputs):
    tree = model_tree(cli, number)
    assert "highspy" in imports(tree)
    modules = {alias.asname or alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
               for alias in node.names if alias.name == "highspy"}
    constructors = {alias.asname or alias.name for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.module == "highspy"
                    for alias in node.names if alias.name == "Highs"}
    objects = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call):
            function = node.value.func
            is_highs = (isinstance(function, ast.Name) and function.id in constructors) or (
                isinstance(function, ast.Attribute) and function.attr == "Highs"
                and isinstance(function.value, ast.Name) and function.value.id in modules)
            if is_highs:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                objects.update(ast.dump(target, include_attributes=False).replace("Store()", "Load()") for target in targets)
    methods = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute)
               and ast.dump(node.func.value, include_attributes=False) in objects}
    assert "run" in methods and methods & {"getSolution", "getInfo"}, "Must run and read a HiGHS instance"
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            assert node.value != 1400 and not (isinstance(node.value, str) and re.search(r"\b1400\b", node.value)), "No canned objective"
    parts = transcript(cli, number)
    meta = metadata(parts, cli, number)
    assert meta["modelsha256"] == hashlib.sha256(model_path(cli, number).read_bytes()).hexdigest()
    harness = certificate(parts["harness-check"])
    validate(harness)
    assert_same(model_outputs[cli, number], harness)
    assert_same(agent_certificate(parts), harness)


@pytest.mark.parametrize("cli,number", RUNS)
def test_d2_failed_solver_cannot_print_optimal_certificate(cli, number):
    path = model_path(cli, number)
    read(path)
    runner = """
import sys
from pathlib import Path
import highspy
def fail(*args, **kwargs):
    raise RuntimeError('injected HiGHS failure')
highspy.Highs.run = fail
path = Path(sys.argv[1])
exec(compile(path.read_bytes(), str(path), 'exec'), {'__name__': '__main__', '__file__': str(path)})
"""
    result = run([sys.executable, "-c", runner, path], DEMO)
    assert not re.search(r"^\s*status:\s*(?:optimal|kOptimal)\s*$", result.stdout, re.M | re.I), (
        "An unavailable solver must not produce a canned optimal certificate")


def test_d2_oracle_rejects_plausible_wrong_certificates():
    correct = ((20, 20, 20, 10, 0, 1400, 1400, 0), frozenset({"assembly", "carpentry"}))
    validate(correct)
    mutations = [(0, 21), (1, 19), (2, -20), (3, 0), (4, 1), (5, 1399), (6, 1401), (7, 1)]
    for index, value in mutations:
        changed = list(correct[0])
        changed[index] = value
        with pytest.raises(AssertionError):
            validate((changed, correct[1]))
    with pytest.raises(AssertionError):
        validate((correct[0], frozenset(ROWS)))


def test_d2_certificate_parser_handles_text_and_json_tool_results():
    sample = ("status: Optimal\nsolution: tables=2e1, chairs=20.0\n"
              "duals: assembly=20, carpentry=10, finishing=0\n"
              "primal objective: 1400\ndual objective: 1400\nduality gap: 0\n"
              "binding constraints: assembly, carpentry\n")
    validate(certificate(sample))
    encoded = json.dumps({"type": "tool_result", "content": sample})
    assert_same(certificate(sample), certificate(encoded))
    for invalid in (sample.replace("chairs=20.0", "chairs=nan"),
                    sample.replace("status: Optimal", "status: infeasible"),
                    sample.replace("dual objective: 1400\n", "")):
        with pytest.raises(AssertionError):
            certificate(invalid)


def test_d3_both_cli_versions_and_models_are_recorded():
    rows = rehearsal_rows()
    for identity in RUNS:
        parts = transcript(*identity)
        meta = metadata(parts, *identity)
        for name in ("version", "model", "date"):
            assert rows[identity][name] == meta[name], f"Rehearsal metadata mismatch: {identity} / {name}"
        output = rendered(parts["agent"])
        assert meta["version"] in output and meta["model"] in output, "CLI provenance must appear in agent evidence"
        agent_certificate(parts)


@pytest.mark.parametrize("cwd_kind", ["demo", "session", "repo"])
def test_d4_reset_is_clean_and_preserves_external_environments(tmp_path, cwd_kind):
    command = reset_line()
    root = tmp_path / "disposable repo with spaces"
    destination = root / RELATIVE
    shutil.copytree(DEMO, destination, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    (root / ".gitignore").write_text(".venv/\nnode_modules/\n", encoding="utf-8")
    success(["git", "init", "-b", "test-cold-open"], root)
    success(["git", "config", "user.email", "test@example.invalid"], root)
    success(["git", "config", "user.name", "Acceptance test"], root)
    success(["git", "add", "."], root)
    success(["git", "commit", "-m", "Disposable test baseline"], root)
    sentinels = [root / "sessions/01-fundamentals/.venv/sentinel", root / "setup/node_modules/sentinel"]
    for path in sentinels:
        path.parent.mkdir(parents=True)
        path.write_text("preserve me", encoding="utf-8")
    for name in ("work/model.py", "work/__pycache__/dirty.pyc", ".claude/settings.local.json", "stray.txt"):
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("dirty run", encoding="utf-8")
    (destination / "README.md").write_text("unstaged edit", encoding="utf-8")
    (destination / "problem.md").write_text("staged edit", encoding="utf-8")
    success(["git", "add", str(RELATIVE / "problem.md")], root)
    cwd = {"demo": destination, "session": root / "sessions/01-fundamentals", "repo": root}[cwd_kind]
    success(["bash", "-c", command], cwd)
    assert success(["git", "status", "--short", "--ignored", "--untracked-files=all", "--", RELATIVE], root) == ""
    for path in sentinels:
        assert path.read_text(encoding="utf-8") == "preserve me"


def test_d4_offline_fallback_models(model_outputs):
    relative_links()
    for identity in RUNS:
        assert not imports(model_tree(*identity)) & NETWORK, "Fallback must not import network modules"
        validate(model_outputs[identity])


def timestamp(value):
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value), "Use UTC date -u +%FT%TZ timestamps"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_a1_two_consecutive_clean_runs_under_five_minutes():
    rows, evidence = rehearsal_rows(), {}
    reset = reset_line()
    for cli, number in RUNS:
        parts = transcript(cli, number)
        meta = metadata(parts, cli, number)
        row = rows[cli, number]
        for name in ("version", "model", "date"):
            assert row[name] == meta[name]
        assert parts["reset"].splitlines()[0].removeprefix("$ ") == reset
        clean = parts["clean-state"].splitlines()
        assert len(clean) == 1 and clean[0].removeprefix("$ ") == "git status --short --ignored --untracked-files=all -- .", "Clean-state status output must be empty"
        invocation = parts["invocation"].removeprefix("$ ")
        command = runbook_command(cli)
        assert invocation.startswith(command), "Live and rehearsed primary commands must be identical"
        suffix = invocation[len(command):].strip()
        if suffix:
            tokens = shlex.split(suffix)
            # Common capture spelling is `2>&1 | tee file` or `> file 2>&1`.
            tokens = [token for token in tokens if token != "2>&1"]
            assert ((tokens[:2] == ["|", "tee"] and len(tokens) == 3)
                    or (len(tokens) == 2 and tokens[0] in {">", ">>", "2>", "&>"})
                    or not tokens), "Only capture tee/redirection may follow the command"
        agent_certificate(parts)
        validate(certificate(parts["harness-check"]))
        assert re.search(r"\buv\s+run\s+python\s+(?:\./)?work/model\.py\b", parts["harness-check"]), "Record the harness re-run command"
        timing = fields(parts["timing"])
        assert {"start", "end", "exit"} <= timing.keys()
        start, end = timestamp(timing["start"]), timestamp(timing["end"])
        elapsed = (end - start).total_seconds() / 60
        assert re.fullmatch(r"\d+(?:\.\d+)?", row["minutes"]), "No estimated or unmeasured timings"
        minutes = float(row["minutes"])
        assert 0 < elapsed < 5 and 0 < minutes < 5 and abs(elapsed - minutes) <= 0.02
        assert timing["exit"] == row["exit"] == "0"
        assert start.date().isoformat() == meta["date"]
        for name in ("start", "end"):
            if name in row:
                assert row[name] == timing[name]
        for name in ("prompt", "problem"):
            path = DEMO / ("prompt.txt" if name == "prompt" else "problem.md")
            assert meta[name + "sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        evidence[cli, number] = (meta, start, end)
    for cli in ("claude", "codex"):
        first, second = evidence[cli, 1], evidence[cli, 2]
        assert timedelta(0) <= second[1] - first[2] <= timedelta(minutes=10)
        for name in ("commit", "promptsha256", "problemsha256"):
            assert first[0][name] == second[0][name], "Consecutive runs must share the same baseline"


@pytest.mark.parametrize("cli,number", RUNS)
def test_a2_only_open_installed_solver(cli, number):
    roots = imports(model_tree(cli, number))
    assert "highspy" in roots and roots <= sys.stdlib_module_names | {"highspy", "numpy"}
    assert not roots & COMMERCIAL
    parts = transcript(cli, number)
    source = rendered(parts["agent"] + "\n" + parts["harness-check"])
    assert not re.search(r"\b(?:pip(?:3)?\s+install|uv\s+(?:add|pip\s+install))\b", source, re.I), "No dependency installs during the run"
    for package in COMMERCIAL:
        assert not re.search(rf"\b(?:import\s+{package}\b|from\s+{package}\b)", source, re.I), "Commercial solver in transcript"
