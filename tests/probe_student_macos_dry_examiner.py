"""The macOS git launcher is not a harmless --version probe before CLT exists."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests/student_setup'))
from student_sandbox import Box, course


def test_dry_run_does_not_launch_git_when_command_line_tools_are_missing(tmp_path):
    box = Box(tmp_path)
    repo = course(tmp_path, {'01-test': ('mise.toml', 'pyproject.toml', 'uv.lock')})
    for tool in ('gh', 'uv', 'mise', 'claude', 'codex', 'curl'):
        box.stub(tool)
    # Like Apple's /usr/bin/git launcher without CLT: invoking it opens a dialog.
    box.stub('git', '#!/bin/sh\necho dialog > "$HOME/clt-dialog-opened"\nexit 1\n')
    box.stub('xcode-select', '#!/bin/sh\nexit 1\n')
    box.stub('sw_vers', '#!/bin/sh\necho 15.0\n')
    result = box.run(['bash', str(repo / 'setup/student/install.sh'), '--dry-run'], FAKE_OS='Darwin')
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (box.home / 'clt-dialog-opened').exists(), result.stdout
