"""Changing installer inputs must select actual tests and the required CI job."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_selector_runs_student_tests_and_exports_required_job(tmp_path):
    spec = importlib.util.spec_from_file_location('impact_examiner', ROOT / 'tools/test-impact/impact.py')
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    for path in ('setup/student/install.sh', 'setup/student/install.ps1', 'setup/student/versions.env',
                 'setup/student/prepare.py', 'sessions/01-fundamentals/uv.lock'):
        plan = module.select(module.Change({path}))
        assert 'student-setup' in plan.units
        assert any('tests/student_setup' in cmd for _, cmd, _ in module.commands(plan))
        output = tmp_path / 'outputs'
        module.github_output(plan, str(output))
        assert 'student_setup=true' in output.read_text().splitlines()
    flow = (ROOT / '.github/workflows/ci.yml').read_text()
    required = flow.split('\n  required:', 1)[1]
    assert 'student-setup' in required.split('\n    steps:', 1)[0]
    assert 'ran_or_not_needed("student-setup"; $student)' in required
