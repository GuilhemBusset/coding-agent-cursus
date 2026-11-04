import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/test-impact"))
import impact


def test_plan_selects_import_check_for_python_and_ruff_config():
    for path in ("probe.py", "sessions/01-fundamentals/exercises/probe.py", "ruff.toml"):
        plan = impact.select(impact.Change({path}))
        assert "imports" in plan.units and not plan.everything, path