"""Independent A2 failure and secret-output assertions."""
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sessions/01-fundamentals/tests'))
from prework_live_agents import Sandbox, local_http

for wrapper in ('bash', 'powershell'):
    with tempfile.TemporaryDirectory() as tmp, local_http() as url:
        machine = Sandbox(Path(tmp) / 'machine', url, agents=('claude',))
        secret = 'EXAMINER_PRIVATE_API_KEY_b5392'
        machine.env.update(ANTHROPIC_API_KEY=secret, OPENAI_API_KEY=secret)
        machine.config['auth_exit'] = 1
        result = machine.run(wrapper)
        assert result.returncode != 0, result.stdout
        assert 'gh-auth: FAIL' in result.stdout and 'result: FAIL' in result.stdout
        for value in (secret, 'PRIVATE_AUTH_STDOUT', 'PRIVATE_AUTH_STDERR', 'PRIVATE_AGENT_STDERR'):
            assert value not in result.stdout + result.stderr, 'Leaked captured output'
        assert '----- BEGIN SETUP SUMMARY -----' in result.stdout
        assert '----- END SETUP SUMMARY -----' in result.stdout
print('PASS: failing auth exits nonzero and reports without secrets')
