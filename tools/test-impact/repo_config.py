#!/usr/bin/env python3
"""The static steps of .github/workflows/checks.yml, for scripts/check-changed.sh: the skill
copies are byte-identical, every shell script parses, the ruleset JSON is valid."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

failed = []
for skill in sorted(p.name for p in (ROOT / ".claude/skills").iterdir() if p.is_dir()):
    pair = [ROOT / f"{d}/skills/{skill}/SKILL.md" for d in (".agents", ".claude")]
    if not all(p.is_file() for p in pair) or pair[0].read_bytes() != pair[1].read_bytes():
        failed.append(f"{skill}: .agents and .claude SKILL.md differ")
scripts = [*sorted(ROOT.glob("scripts/*.sh")), *sorted(ROOT.glob("setup/*.sh")), ROOT / ".githooks/pre-commit", ROOT / ".githooks/pre-push"]
for script in scripts:
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    if result.returncode:
        failed.append(f"{script.relative_to(ROOT)}: {result.stderr.strip()}")
for name in ("setup/pr-only-main.json", "setup/homework-branches.json"):
    try:
        json.loads((ROOT / name).read_text(encoding="utf-8"))
    except ValueError as error:
        failed.append(f"{name}: {error}")
print("\n".join(failed) or "Skill copies identical, shell scripts parse, ruleset JSON valid.")
sys.exit(1 if failed else 0)
