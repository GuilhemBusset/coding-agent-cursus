"""The issue's workflow change must select the complete check set."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_workflow_change_keeps_full_check_selection():
    spec = importlib.util.spec_from_file_location('impact_full_examiner', ROOT / 'tools/test-impact/impact.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    plan = module.select(module.Change({'.github/workflows/student-setup.yml'}))
    assert plan.everything
    assert {'repo-config', 'typecheck', 'engine', 'student-setup', 'turn-in', 'imports'} <= plan.units
    assert plan.sessions and plan.pages
