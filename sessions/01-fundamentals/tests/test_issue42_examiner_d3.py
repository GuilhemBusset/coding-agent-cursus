"""Independent sanitizer round trip and scanner controls."""
import json
import os
import subprocess
import sys
from pathlib import Path


RUNS = Path(__file__).resolve().parents[1] / "cursus/fixtures/runs"


def test_d3_removes_private_values_and_preserves_evidence(tmp_path):
    secret = "gh" + "p_" + "ExaminerOnlyNonCredential123456789"
    address = "examiner" + "@" + "example.invalid"
    original = {"output": ["/home/examiner42/project/check.py", address, secret, "examiner42"],
                "details": {"access_token": "examiner-only-value"}, "keep": "complete Ω evidence\n" * 2000}
    path = tmp_path / "capture.jsonl"
    path.write_text(json.dumps(original) + "\n")
    base = [sys.executable, str(RUNS / "sanitize.py"), "--identity", "examiner42"]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    before = path.read_bytes()
    scan = subprocess.run(base + ["--scan", str(path)], env=env, capture_output=True, text=True)
    assert scan.returncode == 1
    assert path.read_bytes() == before
    assert secret not in scan.stdout + scan.stderr
    subprocess.run(base + [str(path)], env=env, check=True)
    cleaned = json.loads(path.read_text())
    assert cleaned["output"] == ["~/project/check.py", "<email>", "<key>", "<user>"]
    assert cleaned["details"]["access_token"] == "<key>"
    assert cleaned["keep"] == original["keep"]
    once = path.read_bytes()
    subprocess.run(base + [str(path)], env=env, check=True)
    assert path.read_bytes() == once
    subprocess.run(base + ["--scan", str(path)], env=env, check=True)
