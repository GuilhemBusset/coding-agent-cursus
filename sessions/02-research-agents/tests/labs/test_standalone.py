"""Install a detached export, then execute public workflows with network denied."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

SESSION = Path(__file__).resolve().parents[2]

# Propagate denial through the launcher's scrubbed environment and Node's Python
# bridge. Only this test instrumentation changes subprocess environments.
PY_GUARD = '''
import os, socket, subprocess
def denied(*a, **k): raise AssertionError('offline check attempted network')
socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.create_connection = denied
original = subprocess.Popen
def guarded(*a, **k):
    env = dict(k.get('env') or os.environ)
    env['PYTHONPATH'] = os.path.dirname(__file__)
    env['NODE_OPTIONS'] = '--require="' + os.path.join(os.path.dirname(__file__), 'deny.cjs') + '"'
    k['env'] = env
    return original(*a, **k)
subprocess.Popen = guarded
'''
NODE_GUARD = '''
const denied = () => { throw Error('offline check attempted Node network'); };
require('node:net').Socket.prototype.connect = denied;
require('node:http').request = denied;
require('node:https').request = denied;
require('node:dgram').Socket.prototype.send = denied;
globalThis.fetch = denied;
'''


def command(args, cwd, env=None, codes=(0,)):
    result = subprocess.run(list(map(str, args)), cwd=cwd, env=env, capture_output=True,
                            text=True, encoding='utf-8', timeout=240)
    print('COMMAND', list(map(str, args)), '\n', result.stdout, result.stderr)
    assert result.returncode in codes, result.stdout + result.stderr
    return result


def offline(module, *args, session=SESSION, codes=(0,)):
    interpreter = session / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    return offline_command([interpreter if interpreter.exists() else sys.executable,
                            '-m', 'exercises.fixed.' + module, *args], session, codes)


def offline_command(args, session=SESSION, codes=(0,)):
    with TemporaryDirectory(prefix='s2-network-denial-') as temporary:
        guard = Path(temporary)
        (guard / 'sitecustomize.py').write_text(PY_GUARD, encoding='utf-8')
        (guard / 'deny.cjs').write_text(NODE_GUARD, encoding='utf-8')
        env = {k: v for k, v in os.environ.items() if not any(s in k for s in ('KEY', 'TOKEN', 'COURSE_ENDPOINT', 'PYTHONPATH', 'NODE_OPTIONS'))}
        env.update(PYTHONPATH=str(guard), NODE_OPTIONS='--require="' + str(guard / 'deny.cjs') + '"')
        return command(args, session, env, codes)


def test_export_install_and_offline_workflows():
    with TemporaryDirectory(prefix='s2-standalone-') as temporary:
        destination = Path(temporary) / 'export with spaces'
        command([sys.executable, '-m', 'exercises.fixed.export', '--output', destination], SESSION)
        assert not (destination / 'node_modules').exists()
        assert not (destination / '.venv').exists()
        assert sorted(p.name for p in (destination / 'exercises/runs').iterdir()) == ['README.md']
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'VIRTUAL_ENV', 'UV_PROJECT_ENVIRONMENT')}
        command(['uv', 'sync', '--locked'], destination, env)
        npm = shutil.which('npm')
        assert npm
        command([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], destination, env)
        command([npm, 'run', 'typecheck'], destination, env)
        for checkpoint in ('00-model', '01-read', '02-search', '03-memory', '04-audit-stop'):
            assert (destination / 'exercises/fixed/checkpoints' / checkpoint / 'harness/main.ts').is_file()
        # The exported interpreter and cwd establish independence from the clone.
        interpreter = destination / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        program = 'from pathlib import Path; import exercises.fixed.run as r; assert Path(r.__file__).resolve().is_relative_to(Path.cwd()); print(r.__file__)'
        command([interpreter, '-c', program], destination, env)
        # Offline commands use the exported interpreter and exported Node packages.
        offline('checkpoint', 'rejoin', '04-audit-stop', session=destination)
        offline('checkpoint', 'run', '04-audit-stop', '--case', 'c-audit', '--offline', '--name', 'completed', session=destination)
        offline('replay', '--run', destination / 'exercises/fixed/fixtures/faults/transient-read', '--out', destination / 'exercises/runs/replay', session=destination)
        offline('evaluate', 'compare', '--experiment', destination / 'exercises/fixed/examples/prompt.json', '--output', destination / 'exercises/runs/comparison', session=destination, codes=(0, 1))
        result = json.loads((destination / 'exercises/runs/comparison/comparison.json').read_text(encoding='utf-8'))
        assert result['before']['status'] == result['after']['status'] == 'complete'
        assert result['before']['quality_gates_pass']
        # Public tool inspection runs against only exported corpus inputs.
        inspected = offline_command(['node', 'exercises/fixed/bridge/inspect.ts', '--case', 'exercises/cases/c-audit'], destination)
        assert 'check_table' in inspected.stdout


def test_network_guard_covers_python_and_node():
    with TemporaryDirectory(prefix='s2-denial-proof-') as temporary:
        root = Path(temporary)
        (root / 'sitecustomize.py').write_text(PY_GUARD, encoding='utf-8')
        (root / 'deny.cjs').write_text(NODE_GUARD, encoding='utf-8')
        env = dict(os.environ, PYTHONPATH=str(root))
        for program in ("import socket; socket.create_connection(('example.com', 443))",
                        "import subprocess; subprocess.run(['node', '-e', \"fetch('https://example.com')\"], check=True)"):
            result = command([sys.executable, '-c', program], SESSION, env, codes=(1,))
            assert 'offline check attempted' in result.stderr
