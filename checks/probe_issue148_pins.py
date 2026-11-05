"""Verify that the lint cleanup preserves the recorded contracts' bytes."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pinned_contracts_and_recordings_match_the_merge_base():
    base = subprocess.run(
        ["git", "merge-base", "HEAD", "origin/main"], cwd=ROOT,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    result = subprocess.run(
        ["git", "diff", "--exit-code", base, "--",
         "sessions/01-fundamentals/exercises/p00-lab/p00_checker.py",
         "sessions/01-fundamentals/exercises/p00-lab/p00_model.py",
         "sessions/01-fundamentals/exercises/p00-lab/test_p00_contract.py",
         "sessions/*/cursus/demos/*/recorded"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
