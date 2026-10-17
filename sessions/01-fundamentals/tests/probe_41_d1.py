from pathlib import Path
import re


def test_runbooks_have_executable_commands():
    demo = Path(__file__).resolve().parents[1] / 'cursus/demos/agent'
    for name, key in [('loop.md', 'loop'), ('plan-first.md', 'plan'), ('context-bomb.md', 'bomb')]:
        text = (demo / name).read_text()
        for heading in ['Before class', 'Run', 'Expected outcome', 'Fallback', 'Recorded runs', 'Reset']:
            assert '## ' + heading in text
        assert f'agent_demo.py reset {key}' in text
        for cli in ['claude', 'codex']:
            assert re.search(rf'agent_demo.py run {key}\s+--via {cli}', text)
