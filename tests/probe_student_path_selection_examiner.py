"""Selecting a newer uv must not silently downgrade another already-valid tool."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests/student_setup'))
from student_sandbox import Box, course


def test_selecting_local_uv_does_not_run_shadowed_below_floor_mise(tmp_path):
    box = Box(tmp_path)
    box.real('git')
    for tool in ('gh', 'curl', 'uv', 'mise', 'claude', 'codex'):
        box.stub(tool)
    box.os_release('ID=ubuntu\n')
    repo = course(tmp_path, {'01-a': ('mise.toml', 'pyproject.toml', 'uv.lock')})
    local_bin = box.home / '.local/bin'
    local_bin.mkdir(parents=True)
    # A previous user installation coexists with versions selected earlier on PATH.
    # System uv is too old, but system mise already satisfies the floor.
    (local_bin / 'uv').write_bytes((box.bin / 'uv').read_bytes())
    (local_bin / 'uv').chmod(0o755)
    box.stub('uv', version='uv 0.4.0')
    old_mise = local_bin / 'mise'
    old_mise.write_text('#!/bin/sh\nif [ "$1" = --version ]; then echo "mise 2023.12.0"; exit 0; fi\necho BELOW_FLOOR_MISE_USED >> "$STUB_LOG"\nexit 0\n')
    old_mise.chmod(0o755)
    result = box.run(['bash', str(repo / 'setup/student/install.sh'), '--yes', '--agent', 'both', '--no-login'])
    assert 'BELOW_FLOOR_MISE_USED' not in box.calls(), result.stdout + '\n' + '\n'.join(box.calls())
