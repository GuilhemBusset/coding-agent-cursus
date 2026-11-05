"""Independent checks of the repository's effective Ruff policy."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("source", "rule"), [
    ("import os\n", "F401"),
    ("print(missing)\n", "F821"),
    ('import re\nprint(re.findall("x", "x", re.I))\n', "FURB167"),
    ('import subprocess\nsubprocess.run(["false"])\n', "PLW1510"),
    ("callbacks = []\nfor i in range(2):\n    callbacks.append(lambda: i)\n", "B023"),
    ('items = ["a" "b"]\nprint(items)\n', "ISC004"),
])
def test_kept_rules_report_real_mistakes(source, rule):
    result = subprocess.run(
        ["uvx", "ruff@0.17.3", "check", "--output-format", "json",
         "--stdin-filename", "checks/issue148_policy_input.py", "-"],
        cwd=ROOT, input=source, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1, result.stderr
    assert rule in {finding["code"] for finding in json.loads(result.stdout)}


def test_documented_exclusions_accept_the_intended_spelling():
    source = ('values = dict(answer=42)\n'
              'print("\\n".join(["a", "b"]), [x for x in range(3) if x][0], values)\n')
    result = subprocess.run(
        ["uvx", "ruff@0.17.3", "check", "--stdin-filename", "checks/issue148_policy_input.py", "-"],
        cwd=ROOT, input=source, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
