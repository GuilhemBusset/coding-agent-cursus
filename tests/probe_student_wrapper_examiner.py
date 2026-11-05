"""The historical setup command prepares all contract sessions."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests/student_setup'))
from student_sandbox import Box, course, git


def test_historical_wrapper_prepares_all_sessions(tmp_path):
    box = Box(tmp_path)
    box.real('git')
    box.stub('uv')
    box.stub('mise')
    contract = ('mise.toml', 'pyproject.toml', 'uv.lock')
    repo = course(tmp_path, {'01-a': contract, '02-b': contract, '03-incomplete': contract[:-1]})
    result = box.run(['bash', '../../setup/session-01-fundamentals.sh'], cwd=repo / 'sessions/02-b')
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(repo, 'config', '--get', 'core.hooksPath').strip() == '.githooks'
    calls = [c for c in box.calls() if c.startswith('mise ') and not c.startswith('mise --version')]
    assert calls == [f'{cmd} @{repo}/sessions/{s}' for s in ('01-a', '02-b') for cmd in
                     ('mise trust mise.toml', 'mise install', 'mise exec -- uv sync --locked')]
