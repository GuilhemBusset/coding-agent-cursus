"""Exercise the delivered Unix installer and the CI verifier, including a negative version witness."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests/student_setup'))
from student_sandbox import Box, course


def test_unix_installer_outputs_are_accepted_and_below_floor_tools_are_rejected(tmp_path):
    box = Box(tmp_path)
    box.real('git')
    for tool in ('gh', 'uv', 'mise', 'claude', 'codex', 'curl'):
        box.stub(tool)
    box.os_release('ID=ubuntu\n')
    repo = course(tmp_path, {'01-a': ('mise.toml', 'pyproject.toml', 'uv.lock')})
    verifier = ROOT / 'tests/student_setup/ci_verify.py'
    (repo / '.git/info/exclude').write_text('__pycache__/\n')
    base = [sys.executable, str(verifier), '--clone', str(repo)]
    for name in ('first', 'second'):
        out = box.run(['bash', str(repo / 'setup/student/install.sh'), '--yes', '--agent', 'both', '--no-login'])
        assert out.returncode == 0, out.stdout + out.stderr
        (tmp_path / f'{name}.log').write_text(out.stdout)
        if name == 'first':
            assert box.run([*base, '--record', str(tmp_path / 'state')]).returncode == 0
    args = [*base, '--first', str(tmp_path / 'first.log'), '--second', str(tmp_path / 'second.log'), '--before', str(tmp_path / 'state')]
    accepted = box.run(args)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    box.stub('uv', version='uv 0.4.0')
    rejected = box.run(args)
    assert rejected.returncode == 1 and 'uv --version is missing or below its floor' in rejected.stdout
