"""An upgraded user tool must replace the below-floor executable in use."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests/student_setup'))
from student_sandbox import Box, course


def ready(tmp_path):
    box = Box(tmp_path)
    box.real('git')
    for name in ('gh', 'curl', 'uv', 'mise', 'claude', 'codex'):
        box.stub(name)
    box.os_release('ID=ubuntu\nID_LIKE=debian\n')
    repo = course(tmp_path, {'01-one': ('mise.toml', 'pyproject.toml', 'uv.lock')})
    return box, repo


def test_new_user_tool_is_used_instead_of_shadowing_below_floor_copy(tmp_path):
    box, repo = ready(tmp_path)
    box.stub('uv', version='uv 0.4.0')
    fresh = box.home / '.local/bin/uv'
    # A deterministic stand-in for the official installer: install a working new uv
    # in exactly its documented destination, leaving an older system copy untouched.
    payload = '#!/bin/sh\nif [ "$1" = --version ]; then echo "uv 0.13.7"; exit 0; fi\necho NEW_UV_RUN >> "$STUB_LOG"\nwhile [ "$#" -gt 0 ] && [ "$1" != python ]; do shift; done\nshift\nexec "$STUB_PYTHON" "$@"\n'
    installer = f"#!/bin/sh\nmkdir -p '{fresh.parent}'\ncat > '{fresh}' <<'UV_EOF'\n{payload}UV_EOF\nchmod +x '{fresh}'\n"
    box.stub('curl', '#!/bin/sh\nif [ "$1" = --version ]; then echo "curl 8.5.0"; exit 0; fi\ncat <<\'INSTALL_EOF\'\n' + installer + 'INSTALL_EOF\n')
    result = box.run(['bash', str(repo / 'setup/student/install.sh'), '--yes', '--agent', 'claude', '--no-login'])
    assert fresh.exists(), result.stdout + result.stderr
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'NEW_UV_RUN' in box.calls(), result.stdout + '\n' + '\n'.join(box.calls())
    assert 'uv: installed 0.4.0' not in result.stdout


def test_system_package_success_does_not_prove_version_floor(tmp_path):
    import shutil
    box, repo = ready(tmp_path)
    real_git = shutil.which('git')
    # A supported older distro may offer only a git below 2.23 even after apt succeeds.
    box.stub('git', f'#!/bin/sh\nif [ "$1" = --version ]; then echo "git version 2.20.1"; exit 0; fi\nexec "{real_git}" "$@"\n')
    box.stub('apt-get')
    box.stub('sudo', '#!/bin/sh\nexec "$@"\n')
    result = box.run(['bash', str(repo / 'setup/student/install.sh'), '--yes', '--agent', 'claude', '--no-login'])
    assert result.returncode != 0, result.stdout
    assert 'FAILED at system tools' in result.stdout and 'Next:' in result.stdout
