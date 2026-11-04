import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_unsorted_import_fails_and_sorted_import_passes(tmp_path):
    probe = tmp_path / "unsorted_issue149.py"
    probe.write_text("import sys\nimport os\n")
    command = ["uv", "run", "--project", "setup", "--locked", "ruff", "check", "--select", "I", str(probe)]
    failed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert failed.returncode != 0 and "I001" in failed.stdout
    probe.write_text("import os\nimport sys\n")
    passed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert passed.returncode == 0