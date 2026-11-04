import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_session_files_unchanged_and_root_check_passes():
    subprocess.run(["git", "diff", "--exit-code", "origin/main", "--", "sessions/"], cwd=ROOT, check=True)
    subprocess.run(["uv", "run", "--project", "setup", "--locked", "ruff", "check", "--select", "I", "."], cwd=ROOT, check=True)