"""Browser-login commands must retain a controlling terminal with the bootstrap piped in."""
import os
import pty
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests/student_setup'))
from student_sandbox import Box, course


def test_piped_interactive_login_and_check_then_skip_completed_logins(tmp_path):
    box = Box(tmp_path)
    box.real('git')
    box.real('curl')
    box.stub('uv')
    box.stub('mise')
    box.os_release('ID=debian\n')
    repo = course(tmp_path, {'01-a': ('mise.toml', 'pyproject.toml', 'uv.lock', 'exercises/check_setup.py')})
    (repo / 'sessions/01-a/exercises/check_setup.py').write_text("print('EXAMINER_CHECK_EXECUTED')\n")
    for field, value in (('user.name', 'Student'), ('user.email', 'student@example.com')):
        subprocess.run(['git', 'config', '--global', field, value], env=box.env, check=True)
    for name in ('gh', 'claude', 'codex'):
        box.stub(name, f'''#!{sys.executable}
import os, sys
from pathlib import Path
if '--version' in sys.argv:
    print('{name} 99.1.0')
    raise SystemExit(0)
marker = Path.home() / '{name}-logged-in'
if 'status' in sys.argv:
    raise SystemExit(0 if marker.exists() else 1)
if 'login' in sys.argv:
    assert sys.stdin.isatty(), 'login lost its tty'
    print('NEED_APPROVAL', flush=True)
    assert input() == 'approve'
    marker.write_text('logged in')
''')
    box.env.update(BOOTSTRAP_SCRIPT=str(repo / 'setup/student/install.sh'), CURSUS_DIR=str(repo), CURSUS_RAW_BASE=f'file://{repo}')
    for expected_prompts in (3, 0):
        pid, fd = pty.fork()
        if pid == 0:
            os.execvpe('bash', ['bash', '-c', 'cat "$BOOTSTRAP_SCRIPT" | bash -s -- --agent both'], box.env)
        output = b''
        replied = False
        approvals = 0
        status = None
        deadline = time.monotonic() + 20
        try:
            while time.monotonic() < deadline:
                if select.select([fd], [], [], 0.1)[0]:
                    try:
                        data = os.read(fd, 65536)
                    except OSError:
                        break
                    if not data:
                        break
                    output += data
                    if b'Go ahead?' in output and not replied:
                        os.write(fd, b'\n')
                        replied = True
                    while output.count(b'NEED_APPROVAL') > approvals:
                        os.write(fd, b'approve\n')
                        approvals += 1
                done, code = os.waitpid(pid, os.WNOHANG)
                if done:
                    status = os.waitstatus_to_exitcode(code)
                    break
        finally:
            if status is None:
                done, code = os.waitpid(pid, os.WNOHANG)
                if not done:
                    os.kill(pid, signal.SIGTERM)
                    _, code = os.waitpid(pid, 0)
                status = os.waitstatus_to_exitcode(code)
            os.close(fd)
        assert status == 0, output.decode(errors='replace')
        assert approvals == expected_prompts, output.decode(errors='replace')
        assert b'EXAMINER_CHECK_EXECUTED' in output and b'Next steps:' in output
