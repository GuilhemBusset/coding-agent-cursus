"""Independent D3 assertions against local bare repositories."""
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sessions/01-fundamentals/tests'))
from prework_live_agents import Sandbox, local_http

for permission in ('WRITE', 'READ'):
    for wrapper in ('bash', 'powershell'):
        with tempfile.TemporaryDirectory() as tmp, local_http() as url:
            machine = Sandbox(Path(tmp) / 'machine', url, agents=('codex',))
            machine.config['permission'] = permission
            before = machine.snapshot()
            result = machine.run(wrapper)
            assert result.returncode == 0, result.stdout + result.stderr
            assert 'push: PASS' in result.stdout
            assert machine.snapshot() == before, 'Changed student files or refs'
            destination = machine.course if permission == 'WRITE' else machine.fork
            updates = machine.pushes()
            assert len(updates) == 2, updates
            assert all(e['remote'] == str(destination) for e in updates)
            assert all(e['ref'] == 'refs/heads/setup-check/student-47' for e in updates)
            assert updates[0]['tree'] == '' and set(updates[1]['new']) == {'0'}
            assert not machine.git_run('ls-remote', str(destination), 'refs/heads/setup-check/student-47')
print('PASS: actual pushes, fork selection, cleanup and student state')
