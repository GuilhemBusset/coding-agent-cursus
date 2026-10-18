"""Non-OK agent replies fail without revealing captured credentials."""
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sessions/01-fundamentals/tests'))
from prework_live_agents import Sandbox, local_http


@pytest.mark.parametrize('wrapper', ['bash', 'powershell'])
@pytest.mark.parametrize('agent', ['claude', 'codex'])
def test_failed_smoke_and_auth_outputs_never_disclose_secret(tmp_path, wrapper, agent):
    sentinel = 'examiner-24-private-key-3917'
    with local_http() as url:
        box = Sandbox(tmp_path / 'machine', url, agents=(agent,))
        box.env.update(ANTHROPIC_API_KEY=sentinel, OPENAI_API_KEY=sentinel, GH_TOKEN=sentinel)
        box.config['smoke'] = {agent: 'secret'}
        result = box.run(wrapper)
        assert result.returncode != 0
        assert agent + '-smoke: FAIL' in result.stdout
        assert 'result: FAIL' in result.stdout
        for private in (sentinel, 'PRIVATE_AUTH_STDOUT', 'PRIVATE_AUTH_STDERR', 'PRIVATE_AGENT_STDERR', 'PRIVATE_CODEX_PROGRESS'):
            assert private not in result.stdout + result.stderr
