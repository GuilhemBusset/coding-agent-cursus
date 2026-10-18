"""Both public entry points must accept either agent alone."""
from pathlib import Path
import shutil
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sessions/01-fundamentals/tests'))
from prework_live_agents import Sandbox, local_http


@pytest.mark.parametrize('wrapper', ['bash', 'powershell'])
@pytest.mark.parametrize('agent', ['claude', 'codex'])
def test_one_agent_is_sufficient(tmp_path, wrapper, agent):
    other = 'codex' if agent == 'claude' else 'claude'
    with local_http() as url:
        box = Sandbox(tmp_path / 'machine', url, agents=(agent,))
        assert shutil.which(other, path=box.env['PATH']) is None
        result = box.run(wrapper)
        assert result.returncode == 0, result.stdout
        assert agent + '-smoke: PASS replied OK' in result.stdout
        assert other + ': not installed (fine)' in result.stdout
        assert 'result: PASS' in result.stdout and ': FAIL' not in result.stdout
        calls = [e for e in box.events() if e['tool'] == agent and '--version' not in e['args']]
        assert len(calls) == 1
        assert 'Reply with exactly: OK' in calls[0]['args']
        assert not Path(calls[0]['cwd']).is_relative_to(box.repo)
