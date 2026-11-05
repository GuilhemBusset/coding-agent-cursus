"""Exercise a piped bootstrap twice, with existing staged and unstaged work."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests/student_setup'))
from student_sandbox import Box, course, git, tree


def test_piped_rerun_skips_all_six_tools_and_preserves_state(tmp_path):
    box = Box(tmp_path)
    box.real('git')
    box.real('curl')
    for tool in ('gh', 'uv', 'mise', 'claude', 'codex'):
        box.stub(tool)
    box.os_release('ID=debian\n')
    repo = course(tmp_path, {'01-a': ('mise.toml', 'pyproject.toml', 'uv.lock')})
    git(repo, 'switch', '-c', 'feat/student-work')
    (repo / 'work').write_text('staged')
    git(repo, 'add', 'work')
    (repo / 'work').write_text('unstaged')
    before = (git(repo, 'rev-parse', 'HEAD'), git(repo, 'ls-files', '-s'), git(repo, 'status', '--porcelain'), tree(repo, skip=('.git',)))
    for _ in range(2):
        result = box.run(['bash', '-s', '--', '--yes', '--agent', 'both', '--no-login'],
                         input=(repo / 'setup/student/install.sh').read_text(),
                         CURSUS_RAW_BASE=f'file://{repo}', CURSUS_DIR=str(repo))
        assert result.returncode == 0, result.stdout + result.stderr
        for tool in ('git', 'gh', 'uv', 'mise', 'claude', 'codex'):
            assert re.search(rf'^\[setup\] {tool}: present .*left alone$', result.stdout, re.M)
        assert not re.search(r'^\[setup\] .*\b(?:installing|installed|upgrading)\b', result.stdout, re.M)
        assert before == (git(repo, 'rev-parse', 'HEAD'), git(repo, 'ls-files', '-s'), git(repo, 'status', '--porcelain'), tree(repo, skip=('.git',)))
        assert 'result: PASS' not in result.stdout and 'setup check: skipped' in result.stdout
