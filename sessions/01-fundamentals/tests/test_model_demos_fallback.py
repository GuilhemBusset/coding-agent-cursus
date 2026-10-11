"""Issue 30: supplementary GPT-2 stand-in; never proof of the API recording.

Selected by A3's ``test_a3_ or test_d4_`` expression. These tests deliberately
fail if issue 27's committed next_token.json is unavailable. Synthetic changes
are confined to disposable copies and are not recordings or provenance evidence.
Helpers are independent so collection does not depend on the inherited check
file being present. This does not replace that file or its command checks.
The engine must restore tests/test_model_demos.py from e458066^ and bring in
issue 27's committed cursus/fixtures/next_token.json from main before acceptance
can pass. Both repairs are outside this check author's allowed file set. Missing
prerequisites are failures, never skips or generated stand-ins for real evidence.
"""

import ast
from collections import Counter
from copy import deepcopy
from datetime import date
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

import pytest


SESSION = Path(__file__).resolve().parents[1]
DEMO = SESSION / "cursus/demos/model"
FIXTURE = SESSION / "cursus/fixtures/next_token.json"
STAND_IN = "Offline stand-in: GPT-2 next token"
COMMAND = "uv run --offline sampling.py --fixture"
SEEDS = tuple(range(30))

# Installed before executing the script. Log attempts BEFORE raising so caught
# exceptions cannot conceal forbidden I/O. Opening the harness's audit log is
# the only write performed before installation; it lives outside the demo.
AUDIT = r'''
import os
import sys
sys.dont_write_bytecode = True
audit_fd = os.open(os.environ["MODEL_DEMO_AUDIT_LOG"],
                   os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.write(audit_fd, b"audit installed\n")
def audit(event, args):
    if event == "cpython.run_file" and os.path.realpath(args[0]) == os.environ["MODEL_DEMO_SCRIPT"]:
        os.write(audit_fd, b"demo executed\n")
    blocked = event.startswith("socket.")
    blocked |= event in {"subprocess.Popen", "os.system", "os.posix_spawn",
                         "os.exec", "os.fork", "os.forkpty"}
    blocked |= event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename",
                         "os.link", "os.symlink", "os.chmod", "os.chown",
                         "os.truncate", "os.utime"}
    if event == "open":
        mode, flags = args[1], args[2]
        blocked |= isinstance(mode, str) and any(c in mode for c in "wax+")
        blocked |= isinstance(flags, int) and bool(flags & (
            os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
    if blocked:
        os.write(audit_fd, (event + "\n").encode("utf-8"))
        raise RuntimeError("acceptance harness forbids network, children and writes")
sys.addaudithook(audit)
'''

RUNNER = AUDIT + r'''
from pathlib import Path
path = Path(sys.argv[1]).resolve()
sys.argv = [str(path), *sys.argv[2:]]
namespace = {"__name__": "__main__", "__file__": str(path), "__package__": None}
os.write(audit_fd, b"demo executed\n")
exec(compile(path.read_bytes(), str(path), "exec"), namespace)
'''


def read(path):
    assert path.is_file(), f"Missing prerequisite/artifact: {path}"
    return path.read_text(encoding="utf-8")


def constants(base=DEMO):
    values = {}
    for node in ast.parse(read(base / "sampling.py")).body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    try:
                        values[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        pass
    return values


def fixture(path=FIXTURE):
    data = json.loads(read(path))
    matches = [item for item in data["prompts"] if item["id"] == "open-ended"]
    assert len(matches) == 1, "Fixture must contain exactly one open-ended prompt"
    entry = matches[0]
    assert len(entry["top"]) == 20
    assert all(isinstance(t["text"], str) and math.isfinite(t["logit"])
               for t in entry["top"])
    return data, entry


def probability(entry, temperature):
    logits = [item["logit"] for item in entry["top"]]
    peak = max(logits)
    weights = [math.exp((value - peak) / temperature) for value in logits]
    total = math.fsum(weights)
    return [weight / total for weight in weights]


def environment(tmp_path):
    env = os.environ.copy()
    for name in list(env):
        if ("API_KEY" in name or name.startswith(("MODEL_DEMO_", "DEMO_TEST_", "PYTEST_"))
                or name in {"ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "PYTHONPATH",
                            "PYTHONHOME", "VIRTUAL_ENV"}
                or name.lower().endswith("_proxy")):
            env.pop(name, None)
    env.update(UV_OFFLINE="1", UV_PYTHON_DOWNLOADS="never", UV_PYTHON=sys.executable,
               UV_CACHE_DIR=str(tmp_path / "uv-cache"), PYTHONDONTWRITEBYTECODE="1",
               PYTHONIOENCODING="utf-8", MODEL_DEMO_AUDIT_LOG=str(tmp_path / "audit.log"),
               MODEL_DEMO_SCRIPT=str((DEMO / "sampling.py").resolve()))
    return env


def invoke(argv, cwd, env):
    result = subprocess.run([str(arg) for arg in argv], cwd=cwd, env=env,
                            stdin=subprocess.DEVNULL, capture_output=True,
                            timeout=60, check=False)
    audit_log = Path(env["MODEL_DEMO_AUDIT_LOG"])
    assert audit_log.is_file(), "The script must execute under the audit hook"
    assert read(audit_log) == "audit installed\ndemo executed\n", (
        f"Audit did not cover the demo, or forbidden I/O was attempted: {read(audit_log)}")
    return result


def script(tmp_path, args, base=DEMO, cwd=None):
    read(base / "sampling.py")
    env = environment(tmp_path)
    env["MODEL_DEMO_SCRIPT"] = str((base / "sampling.py").resolve())
    return invoke([sys.executable, "-I", "-B", "-c", RUNNER, base / "sampling.py", *args],
                  cwd or base, env)


def success(result):
    assert result.returncode == 0, (
        f"exit {result.returncode}\n{result.stdout.decode()}\n{result.stderr.decode()}")
    assert not result.stderr, result.stderr.decode()
    return result.stdout.decode("utf-8")


def section(heading):
    source = read(DEMO / "sampling.md")
    matches = list(re.finditer(r"^##\s+([^\n]+)\n", source, re.M))
    selected = [i for i, match in enumerate(matches) if match[1].strip() == heading]
    assert len(selected) == 1, f"Need one ## {heading} section"
    i = selected[0]
    return source[matches[i].end():matches[i + 1].start() if i + 1 < len(matches) else len(source)]


def blocks(source):
    return re.findall(r"^```[^\n]*\n(.*?)^```\s*$", source, re.M | re.S)


def columns(output, low, high):
    # Parse repr(string) rather than splitting on '|': that character may be a
    # token, and escapes/newlines must remain visible rather than corrupt rows.
    quoted = r'''(?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")'''
    row_pattern = re.compile(rf"^\s*(\d+)\s+({quoted})\s*\|\s*({quoted})\s*$")
    rows = [match for line in output.splitlines() if (match := row_pattern.fullmatch(line))]
    numbered = [line for line in output.splitlines() if re.match(r"^\s*\d+\s+", line)]
    assert len(numbered) == len(rows) == 5, output
    assert [int(match[1]) for match in rows] == list(range(1, 6)), output
    left, right = [], []
    for match in rows:
        for rendered, target in ((match[2], left), (match[3], right)):
            token = ast.literal_eval(rendered)
            assert isinstance(token, str) and rendered == repr(token), rendered
            target.append(token)
    summaries = re.findall(r"^distinct answers at temperature ([^:]+): (\d+) of 5$", output, re.M)
    assert len(summaries) == 2, output
    assert [(float(t), int(k)) for t, k in summaries] == [
        (low, len(set(left))), (high, len(set(right)))], output
    return left, right


def snapshot(folder):
    return {str(path.relative_to(folder)): path.read_bytes()
            for path in folder.rglob("*") if path.is_file()}


def sandbox(tmp_path, with_fixture=True):
    base = tmp_path / "session with spaces/cursus/demos/model"
    shutil.copytree(DEMO, base, ignore=shutil.ignore_patterns("work", "__pycache__"))
    if with_fixture:
        target = base.parents[1] / "fixtures/next_token.json"
        target.parent.mkdir(parents=True)
        target.write_text(read(FIXTURE), encoding="utf-8")
    return base


def default_seed():
    value = constants().get("SEED")
    assert type(value) is int, "sampling.py must declare its default SEED"
    return value


def test_a3_engine_prerequisites_are_present():
    prerequisites = {
        SESSION / "tests/test_model_demos.py":
            "engine must restore the inherited locked checks from e458066^; "
            "all six command checks still require this file",
        FIXTURE:
            "engine must bring the branch up to date with main to include "
            "issue 27's committed next_token.json",
    }
    missing = [f"{path.relative_to(SESSION)}: {remedy}"
               for path, remedy in prerequisites.items() if not path.is_file()]
    assert not missing, "Missing engine prerequisites:\n" + "\n".join(missing)


def test_d4_fixture_five_paired_draws_and_argmax_without_a_key(tmp_path):
    _, entry = fixture()
    assert constants().get("FIXTURE_PROMPT") == "open-ended"
    output = success(script(tmp_path, ["--fixture", "--low", "0.0", "--high", "1.0",
                                       "--seed", "731"], cwd=tmp_path))
    left, right = columns(output, 0.0, 1.0)
    top = max(entry["top"], key=lambda item: item["logit"])["text"]
    assert left == [top] * 5
    assert set(right) <= {item["text"] for item in entry["top"]}


def test_d4_fixture_temperature_changes_the_seeded_distribution(tmp_path):
    _, entry = fixture()
    allowed = {item["text"] for item in entry["top"]}
    best = max(range(20), key=lambda i: entry["top"][i]["logit"])
    top = entry["top"][best]["text"]
    pooled = {1.0: [], 0.2: []}
    high_columns = []
    for temperature in pooled:
        for seed in SEEDS:
            output = success(script(tmp_path, ["--fixture", "--low", "0.0", "--high",
                                               str(temperature), "--seed", str(seed)]))
            left, right = columns(output, 0.0, temperature)
            assert left == [top] * 5 and set(right) <= allowed
            pooled[temperature].extend(right)
            if temperature == 1.0:
                high_columns.append(tuple(right))
    assert len(pooled[1.0]) == 150 and len(set(pooled[1.0])) >= 3
    assert len(set(high_columns)) >= 2, "Changing seed must affect the sampled column"
    frequency = Counter(pooled[1.0])[top] / 150
    assert abs(frequency - probability(entry, 1.0)[best]) <= 0.12
    assert Counter(pooled[0.2])[top] / 150 >= frequency


def test_d4_fixture_same_seed_is_byte_identical_and_default_is_explicit(tmp_path):
    args = ["--fixture", "--seed", "19471", "--low", "0.0", "--high", "0.7"]
    first, second = script(tmp_path, args), script(tmp_path, args)
    columns(success(first), 0.0, 0.7)
    success(second)
    assert first.stdout == second.stdout
    implicit = script(tmp_path, ["--fixture"])
    explicit = script(tmp_path, ["--fixture", "--seed", str(default_seed())])
    success(implicit)
    success(explicit)
    assert implicit.stdout == explicit.stdout


def test_d4_fixture_reads_changed_tokens_and_logits_from_session_local_copy(tmp_path):
    # A hard-coded default transcript/distribution cannot satisfy this test.
    data, original = fixture()
    changed = deepcopy(data)
    entry = next(item for item in changed["prompts"] if item["id"] == original["id"])
    for i, token in enumerate(entry["top"]):
        token["text"] = f" synthetic token {i} | 'λ'\n"
        token["logit"] = 50.0 if i == 17 else -50.0 - i
    expected = entry["top"][17]["text"]
    entry["top"].sort(key=lambda token: (-token["logit"], token["id"]))
    entry["logsumexp"] = round(50.0 + math.log(1.25), 3)
    base = sandbox(tmp_path)
    path = base.parents[1] / "fixtures/next_token.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    before = snapshot(base.parents[1])
    output = success(script(tmp_path, ["--fixture", "--low", "0.0", "--high", "1.0",
                                       "--seed", "813"], base=base, cwd=tmp_path))
    left, right = columns(output, 0.0, 1.0)
    assert left == right == [expected] * 5
    assert snapshot(base.parents[1]) == before, "Stand-in must not write any file"


def test_d4_fixture_documented_command_runs_literally_with_audit(tmp_path):
    command_blocks = blocks(section(STAND_IN))
    assert len(command_blocks) == 1 and command_blocks[0].strip() == COMMAND
    assert shutil.which("uv"), "Engine prerequisite: real uv on PATH"
    # This hook directory is test instrumentation only. It does not locate the
    # demo or any dependency, and affects only the child launched by real uv.
    hook = tmp_path / "audit hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(AUDIT, encoding="utf-8")
    env = environment(tmp_path)
    env["PYTHONPATH"] = str(hook)
    result = invoke(shlex.split(command_blocks[0]), DEMO, env)
    success(result)
    direct = script(tmp_path, ["--fixture", "--seed", str(default_seed())])
    success(direct)
    assert result.stdout == direct.stdout


@pytest.mark.parametrize("other", ["--record", "--replay"])
def test_d4_fixture_rejects_record_and_replay_without_changing_recorded(tmp_path, other):
    base = sandbox(tmp_path, with_fixture=False)
    before = snapshot(base / "recorded")
    result = script(tmp_path, ["--fixture", other], base=base)
    assert result.returncode == 2
    assert not result.stdout and "--fixture" in result.stderr.decode()
    assert other in result.stderr.decode() and "Traceback" not in result.stderr.decode()
    assert "unrecognized arguments" not in result.stderr.decode()
    assert snapshot(base / "recorded") == before


def test_d4_fixture_documented_seed_and_distinct_counts_are_observed(tmp_path):
    content = section(STAND_IN)
    prose = re.sub(r"^```[^\n]*\n.*?^```\s*$", "", content, flags=re.M | re.S)
    seed = default_seed()
    assert re.search(rf"\bseed\b[^\d\n]{{0,32}}{seed}(?!\d)", prose, re.I), (
        "Document the seed used for the stand-in observations")
    output = success(script(tmp_path, ["--fixture", "--seed", str(seed)]))
    summaries = [line for line in output.splitlines()
                 if line.startswith("distinct answers at temperature ")]
    assert len(summaries) == 2
    documented = re.findall(r"distinct answers at temperature [^:\n`]+: \d+ of 5", content)
    assert documented == summaries, "Document actual counts for the documented seed"


def test_d4_fixture_top_twenty_qualification_and_vocabulary_mass():
    _, entry = fixture()
    content = section(STAND_IN)
    assert re.search(r"top[ -]+(?:20|twenty)\b", content, re.I)
    assert re.search(r"renormali[sz]", content, re.I)
    if "logsumexp" in entry:
        mass = math.fsum(math.exp(token["logit"] - entry["logsumexp"])
                         for token in entry["top"])
        assert 0 < mass <= 1.001, "Invalid full-vocabulary logsumexp"
        paragraphs = [paragraph for paragraph in re.split(r"\n\s*\n", content)
                      if re.search(r"mass|probability|vocabulary", paragraph, re.I)]
        values = []
        for paragraph in paragraphs:
            values.extend(float(number) / 100 for number in re.findall(
                r"(\d+(?:\.\d+)?)\s*(?:%|percent|per cent)", paragraph, re.I))
            values.extend(float(number) for number in re.findall(r"\b0\.\d+\b", paragraph))
        assert any(abs(value - mass) <= 0.006 for value in values), (
            f"Document top-20 share of full-vocabulary mass (approximately {mass:.4%})")


def test_d4_missing_replay_names_owner_step_and_supplementary_fixture(tmp_path):
    base = sandbox(tmp_path, with_fixture=False)
    (base / "recorded/sampling.json").unlink(missing_ok=True)
    result = script(tmp_path, ["--replay"], base=base)
    assert result.returncode == 1
    lines = (result.stdout + result.stderr).decode().strip().splitlines()
    assert len(lines) == 1
    assert all(word in lines[0].lower() for word in ("missing", "--record", "key"))
    assert COMMAND in lines[0] and "gpt-2" in lines[0].lower()
    assert "Traceback" not in lines[0]


def test_d4_stand_in_is_supplementary_and_api_recording_status_is_honest():
    recorded = (DEMO / "recorded/sampling.json").is_file()
    for name in ("README.md", "sampling.md"):
        source = read(DEMO / name)
        assert not re.search(r"no\s+offline\s+fallback", source, re.I), name
        assert re.search(r"stand[- ]in|--fixture", source, re.I), name
        if not recorded:
            paragraphs = re.split(r"\n\s*\n", source)
            assert any(re.search(r"pending", p, re.I) and re.search(r"record", p, re.I)
                       for p in paragraphs), f"{name}: API recording is still pending"
    recorded_section = section("Recorded runs")
    assert "openai-community/gpt2" not in recorded_section
    assert "next_token.json" not in recorded_section
    if not recorded:
        assert "pending: record with a key" in recorded_section


def assert_provenance(output, content, data, seed):
    meta = data["meta"]
    models = [model for model in meta["models"] if model["id"] == "openai-community/gpt2"]
    assert len(models) == 1
    model = models[0]
    assert re.fullmatch(r"[0-9a-f]{40}", model["revision"])
    assert date.fromisoformat(meta["date"]) <= date.today()
    header = output.splitlines()[0]
    assert model["id"] in header and meta["date"] in header
    prefixes = re.findall(r"\b[0-9a-f]{7,40}\b", header)
    assert any(model["revision"].startswith(prefix) for prefix in prefixes)
    assert "top-20 renormalised" in header.lower() and "not the api" in header.lower()
    assert re.search(rf"\bseed\b[^\d\n]{{0,16}}{seed}(?!\d)", header, re.I)
    for value in (model["id"], model["revision"], meta["date"]):
        assert value in content, f"Stand-in section must record fixture provenance: {value}"


def test_a3_fixture_header_and_runbook_show_model_revision_and_run_date(tmp_path):
    data, _ = fixture()
    seed = default_seed()
    output = success(script(tmp_path, ["--fixture"]))
    assert_provenance(output, section(STAND_IN), data, seed)


def test_a3_fixture_header_reads_provenance_from_the_fixture(tmp_path):
    data, _ = fixture()
    base = sandbox(tmp_path)
    data["meta"]["date"] = "2001-02-03"
    model = next(model for model in data["meta"]["models"]
                 if model["id"] == "openai-community/gpt2")
    model["revision"] = "fedcba9876543210" * 2 + "fedcba98"
    (base.parents[1] / "fixtures/next_token.json").write_text(json.dumps(data), encoding="utf-8")
    seed = 9871
    output = success(script(tmp_path, ["--fixture", "--seed", str(seed)], base=base))
    # Runbook is unchanged in this disposable copy; only verify the dynamic
    # header against the changed metadata, not the real runbook's observations.
    assert_provenance(output, " ".join((model["id"], model["revision"], data["meta"]["date"])),
                      data, seed)
