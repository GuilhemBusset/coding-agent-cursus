"""The cold-open demo's recorded fallback, and its reset line.

If the live run fails, the instructor shows a recorded run and runs the model file the
agent wrote. Each recorded model must still solve the LP offline, its output must be an
optimal certificate checked here by an independent LP oracle (feasibility and duality,
not an answer string), and the transcript must belong to that model file and show the
agent's own successful run. All commands are offline; git mutations occur only in a
disposable test repository.
"""

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SESSION = Path(__file__).resolve().parents[2]
RELATIVE = Path("sessions/01-fundamentals/cursus/demos/cold-open")
DEMO = SESSION / "cursus/demos/cold-open"
RUNS = [(cli, number) for cli in ("claude", "codex") for number in (1, 2)]
C = (40, 30)
A = ((1, 1), (2, 1), (1, 3))
B = (40, 60, 90)
ROWS = ("assembly", "carpentry", "finishing")
TOL = 1e-6
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
SECTIONS = ("meta", "reset", "clean-state", "invocation", "agent", "harness-check", "timing")
# A network-denying audit hook also covers indirect network attempts. No CLI or uv
# process is involved: the already provisioned session interpreter runs the model.
OFFLINE_RUNNER = """
import sys
from pathlib import Path
def offline(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname'}:
        raise RuntimeError('network forbidden in recorded fallback')
sys.addaudithook(offline)
path = Path(sys.argv[1])
exec(compile(path.read_bytes(), str(path), 'exec'), {'__name__': '__main__', '__file__': str(path)})
"""


def read(path):
    assert path.is_file(), f"Missing required artifact: {path}"
    source = path.read_text(encoding="utf-8")
    assert source.strip(), f"Empty artifact: {path}"
    return source


def child_env():
    env = os.environ.copy()
    for name in list(env):
        if name.startswith("GIT_") or name in {"PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"}:
            env.pop(name)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", UV_OFFLINE="1")
    return env


def success(args, cwd):
    result = subprocess.run([str(arg) for arg in args], cwd=cwd, env=child_env(),
                            capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert result.returncode == 0, f"{args}\n{result.stdout}\n{result.stderr}"
    return result.stdout


def model_path(cli, number):
    return DEMO / "recorded" / f"{cli}_run{number}_model.py"


def transcript(cli, number):
    source = read(DEMO / "recorded" / f"{cli}-run{number}.txt")
    matches = list(re.finditer(r"^===\s*([\w-]+)\s*===\s*$", source, re.MULTILINE))
    assert [match[1] for match in matches] == list(SECTIONS), "Need the seven ordered evidence sections"
    return {match[1]: source[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(source)].strip()
            for i, match in enumerate(matches)}


def fields(source):
    result = {}
    for line in source.splitlines():
        match = re.fullmatch(r"\s*([^:=]+?)\s*[:=]\s*(.*?)\s*", line)
        assert match, f"Expected evidence key: value, got {line!r}"
        result[re.sub(r"[^a-z0-9]", "", match[1].lower())] = match[2].strip("`")
    return result


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
    matches = list(re.finditer("^" + pattern, rendered(source), re.MULTILINE | re.IGNORECASE))
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
                     source[:command.end()], re.IGNORECASE), "Need a recorded tool call, not just assistant prose"
    result = certificate(source[command.end():])
    validate(result)
    return result


def assert_same(left, right):
    assert left[0] == pytest.approx(right[0], rel=0, abs=TOL)
    assert left[1] == right[1]


@pytest.mark.parametrize("cli,number", RUNS)
def test_recorded_fallback_solves_offline_and_matches_its_transcript(cli, number):
    path = model_path(cli, number)
    solved = certificate(success([sys.executable, "-c", OFFLINE_RUNNER, path], DEMO))
    validate(solved)
    parts = transcript(cli, number)
    assert fields(parts["meta"])["modelsha256"] == hashlib.sha256(path.read_bytes()).hexdigest(), (
        "The transcript must belong to this model file")
    assert_same(certificate(parts["harness-check"]), solved)
    assert_same(agent_certificate(parts), solved)


def test_reset_cleans_the_demo_and_nothing_else(tmp_path):
    source = read(DEMO / "README.md")
    section = re.search(r"^## Reset\s*\n(.*?)(?=^## |\Z)", source, re.MULTILINE | re.DOTALL)
    assert section, "Missing ## Reset"
    blocks = re.findall(r"^```[^\n]*\n(.*?)^```\s*$", section[1], re.MULTILINE | re.DOTALL)
    assert len(blocks) == 1, "One reset command block"
    command = blocks[0].strip()
    assert str(SESSION.parents[1]) not in command, "Reset must be checkout-relative"
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
    success(["bash", "-c", command], destination)
    assert success(["git", "status", "--short", "--ignored", "--untracked-files=all", "--", RELATIVE], root) == ""
    for path in sentinels:
        assert path.read_text(encoding="utf-8") == "preserve me"
