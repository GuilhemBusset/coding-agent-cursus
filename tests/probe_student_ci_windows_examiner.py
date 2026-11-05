"""Exercise PowerShell iex options and the delivered CI verifier on the available host."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests/student_setup'))
from student_sandbox import Box, course, powershell


def test_windows_iex_environment_contract_and_ci_verifier(tmp_path):
    box = Box(tmp_path)
    box.real('git')
    for tool in ('gh', 'uv', 'mise', 'claude', 'codex'):
        box.stub(tool)
    repo = course(tmp_path, {'01-a': ('mise.toml', 'pyproject.toml', 'uv.lock')})
    env = dict(OS='Windows_NT', USERPROFILE=str(box.home), XDG_CACHE_HOME=str(tmp_path / 'cache'),
               CURSUS_YES='1', CURSUS_AGENT='both', CURSUS_NO_LOGIN='1', CURSUS_DIR=str(repo), CURSUS_RAW_BASE=str(repo))
    command = "Get-Content -Raw '" + str(repo / 'setup/student/install.ps1').replace("'", "''") + "' | Invoke-Expression; exit $LASTEXITCODE"
    (repo / '.git/info/exclude').write_text('__pycache__/\n')
    base = [sys.executable, str(ROOT / 'tests/student_setup/ci_verify.py'), '--clone', str(repo)]
    for name in ('first', 'second'):
        result = box.run([powershell(), '-NoProfile', '-Command', command], **env)
        assert result.returncode == 0, result.stdout + result.stderr
        (tmp_path / f'{name}.log').write_text(result.stdout)
        if name == 'first':
            assert box.run([*base, '--record', str(tmp_path / 'state')]).returncode == 0
    result = box.run([*base, '--first', str(tmp_path / 'first.log'), '--second', str(tmp_path / 'second.log'), '--before', str(tmp_path / 'state'), '--preinstalled', 'git,gh'])
    assert result.returncode == 0, result.stdout + result.stderr
