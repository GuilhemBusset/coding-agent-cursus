"""Run shared Python with a complete and an incomplete session fixture."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests/student_setup'))
from student_sandbox import STUDENT, Box, course


def test_discovery_and_failure_recovery(tmp_path):
    box = Box(tmp_path)
    box.real('git')
    box.stub('mise')
    contract = ('mise.toml', 'pyproject.toml', 'uv.lock')
    repo = course(tmp_path, {'01-a': contract, '02-b': contract, '03-incomplete': contract[:-1]})
    args = [sys.executable, str(STUDENT / 'prepare.py'), '--repo', str(repo), '--no-check']
    failed = box.run(args, MISE_FAIL=f'install @{repo}/sessions/02-b')
    assert failed.returncode == 1 and 'Next: cd sessions/02-b && mise install' in failed.stdout
    box.log.write_text('')
    good = box.run(args)
    assert good.returncode == 0, good.stdout + good.stderr
    calls = [c for c in box.calls() if c.startswith('mise ')]
    assert calls == [f'{cmd} @{repo}/sessions/{s}' for s in ('01-a', '02-b') for cmd in
                     ('mise trust mise.toml', 'mise install', 'mise exec -- uv sync --locked')]
