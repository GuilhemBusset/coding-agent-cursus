"""Independent A1 assertions, reusing only the builder's machine fixture."""
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sessions/01-fundamentals/tests'))
from prework_live_agents import Sandbox, local_http

for agent, absent in (('claude', 'codex'), ('codex', 'claude')):
    with tempfile.TemporaryDirectory() as tmp, local_http() as url:
        machine = Sandbox(Path(tmp) / 'machine', url, agents=(agent,))
        assert not (machine.bin / absent).exists()
        for wrapper in ('bash', 'powershell'):
            result = machine.run(wrapper)
            assert result.returncode == 0, result.stdout + result.stderr
            assert 'result: PASS' in result.stdout
            assert agent + '-smoke: PASS replied OK' in result.stdout
            assert absent + ': not installed (fine)' in result.stdout
            assert absent + '-smoke:' not in result.stdout
print('PASS: both wrappers accept either agent alone')
