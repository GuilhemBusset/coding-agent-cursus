import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_locked_ruff_version_and_repository_imports():
    subprocess.run(["uv", "lock", "--project", "setup", "--check"], cwd=ROOT, check=True)
    version = subprocess.run(["uv", "run", "--project", "setup", "--locked", "ruff", "--version"], cwd=ROOT, check=True, capture_output=True, text=True)
    assert version.stdout.strip() == "ruff 0.17.3"
    subprocess.run(["uv", "run", "--project", "setup", "--locked", "ruff", "check", "--select", "I", "."], cwd=ROOT, check=True)