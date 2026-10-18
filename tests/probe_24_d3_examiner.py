"""Observe real temporary Git ref updates, not merely the printed push verdict."""
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sessions/01-fundamentals/tests'))
from prework_live_agents import Sandbox, local_http


@pytest.mark.parametrize('wrapper', ['bash', 'powershell'])
@pytest.mark.parametrize('permission', ['WRITE', 'READ'])
def test_push_permission_roundtrip_preserves_checkout(tmp_path, wrapper, permission):
    with local_http() as url:
        box = Sandbox(tmp_path / 'machine', url)
        box.config['permission'] = permission
        before = box.snapshot()
        result = box.run(wrapper)
        assert result.returncode == 0, result.stdout
        assert 'push: PASS' in result.stdout
        assert before == box.snapshot()
        remote = box.course if permission == 'WRITE' else box.fork
        events = box.pushes()
        assert len(events) == 2
        assert all(e['remote'] == str(remote) for e in events)
        assert all(e['ref'] == 'refs/heads/setup-check/student-47' for e in events)
        assert set(events[0]['old']) == {'0'} and events[0]['tree'] == ''
        assert events[1]['old'] == events[0]['new'] and set(events[1]['new']) == {'0'}
        assert box.git_run('ls-remote', str(remote), 'refs/heads/setup-check/student-47') == ''


@pytest.mark.parametrize('wrapper', ['bash', 'powershell'])
def test_rejected_push_cannot_pass(tmp_path, wrapper):
    with local_http() as url:
        box = Sandbox(tmp_path / 'machine', url)
        box.hook(box.course, reject='all')
        before = box.snapshot()
        result = box.run(wrapper)
        assert result.returncode != 0
        assert 'push: FAIL' in result.stdout and 'push: PASS' not in result.stdout
        assert before == box.snapshot()
