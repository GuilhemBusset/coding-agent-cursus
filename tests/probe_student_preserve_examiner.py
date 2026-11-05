"""Preparing an existing clone must preserve edits to tracked file modes too."""
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests/student_setup'))
from student_sandbox import Box, course, git, tree


def test_existing_clone_preserves_uncommitted_hook_mode_change(tmp_path):
    box = Box(tmp_path)
    box.real('git')
    for tool in ('gh', 'uv', 'mise', 'claude', 'codex', 'curl'):
        box.stub(tool)
    box.os_release('ID=debian\n')
    repo = course(tmp_path, {'01-test': ('mise.toml', 'pyproject.toml', 'uv.lock')})
    git(repo, 'switch', '-c', 'feat/homework')
    hook = repo / '.githooks/pre-commit'
    hook.chmod(hook.stat().st_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    (repo / 'sessions/01-test/uv.lock').write_text('staged edit\n')
    git(repo, 'add', 'sessions/01-test/uv.lock')
    (repo / 'sessions/01-test/uv.lock').write_text('unstaged edit\n')
    (repo / 'notes.txt').write_text('untracked work\n')
    def state():
        return (git(repo, 'symbolic-ref', 'HEAD'), git(repo, 'rev-parse', 'HEAD'),
                git(repo, 'ls-files', '-s'), git(repo, 'diff'), git(repo, 'diff', '--cached'),
                tree(repo, skip=('.git',)))
    before = state()
    result = box.run(['bash', str(repo / 'setup/student/install.sh'), '--yes', '--agent', 'both', '--no-login'])
    assert state() == before, result.stdout + '\n' + git(repo, 'diff')
