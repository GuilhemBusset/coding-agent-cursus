"""Independent boundary probes for the actual bootstrap entry point."""
import os
import pty
import select
import signal
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests/student_setup'))
from student_sandbox import Box, course, powershell


def ready(tmp_path):
    box = Box(tmp_path)
    box.real('git')
    for name in ('gh', 'curl', 'uv', 'mise', 'claude', 'codex'):
        box.stub(name)
    box.os_release('ID=ubuntu\nID_LIKE=debian\n')
    repo = course(tmp_path, {'01-one': ('mise.toml', 'pyproject.toml', 'uv.lock')})
    return box, repo


def terminal_run(argv, box, repo):
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(repo)
        os.execvpe(argv[0], argv, box.env)
    output = b''
    deadline = time.monotonic() + 15
    status = None
    try:
        while time.monotonic() < deadline:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output += chunk
                if b'Your name, for your git commits' in output:
                    break
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
    return status, output.decode(errors='replace')


@pytest.mark.parametrize('shell', ['bash', 'powershell'])
def test_noninteractive_options_never_prompt_even_with_a_terminal(tmp_path, shell):
    box, repo = ready(tmp_path)
    if shell == 'bash':
        argv = ['bash', str(repo / 'setup/student/install.sh'), '--yes', '--agent', 'both', '--no-login']
    else:
        box.env.update(OS='Windows_NT', USERPROFILE=str(box.home), XDG_CACHE_HOME=str(box.root / 'ps-cache'))
        argv = [powershell(), '-NoProfile', '-File', str(repo / 'setup/student/install.ps1'), '-Yes', '-Agent', 'both', '-NoLogin']
    code, output = terminal_run(argv, box, repo)
    assert 'Your name, for your git commits' not in output, output
    assert code == 0, output
