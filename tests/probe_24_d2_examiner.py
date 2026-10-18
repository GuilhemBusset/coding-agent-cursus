"""Independent assertions over the delivered wrappers; fixtures only replace services."""
from pathlib import Path
import re
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sessions/01-fundamentals/tests'))
from prework_live_agents import Sandbox, local_http


@pytest.mark.parametrize('wrapper', ['bash', 'powershell'])
def test_tool_auth_network_and_summary(tmp_path, wrapper):
    with local_http(403) as url:
        box = Sandbox(tmp_path / 'machine', url)
        result = box.run(wrapper)
        assert result.returncode == 0, result.stdout
        before, tail = result.stdout.split('----- BEGIN SETUP SUMMARY -----')
        summary, after = tail.split('----- END SETUP SUMMARY -----')
        assert not after.strip()
        for tool in ('git', 'gh', 'uv', 'mise', 'claude', 'codex'):
            line = re.search(r'^' + tool + r': PASS (\d+\.\d+[^\n]*)', before, re.M)
            assert line, (tool, before)
            assert line.group(0) in summary
        for text in ('gh-auth: PASS', 'reachable (HTTP 403)', 'claude-smoke: PASS', 'codex-smoke: PASS', 'result: PASS'):
            assert text in summary
        assert any(e['tool'] == 'gh' and e['args'] == ['auth', 'status'] for e in box.events())


@pytest.mark.parametrize('wrapper', ['bash', 'powershell'])
def test_auth_failure_is_reported_without_aborting_other_checks(tmp_path, wrapper):
    with local_http() as url:
        box = Sandbox(tmp_path / 'machine', url)
        box.config['auth_exit'] = 9
        result = box.run(wrapper)
        assert result.returncode != 0
        for text in ('gh-auth: FAIL', 'push: FAIL', 'claude-smoke: PASS', 'codex-smoke: PASS', 'result: FAIL', '----- END SETUP SUMMARY -----'):
            assert text in result.stdout
        assert not box.pushes()
