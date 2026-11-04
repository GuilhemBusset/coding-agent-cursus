import json
import subprocess
import sys
from pathlib import Path


def test_replay_reports_recorded_versions_and_models():
    demo = Path(__file__).resolve().parents[1] / 'cursus/demos/agent'
    for name in ['loop', 'plan', 'bomb']:
        for cli in ['claude', 'codex']:
            meta = json.loads((demo / f'recorded/{name}-{cli}-run1.meta.json').read_text())
            proc = subprocess.run([sys.executable, str(demo / 'agent_demo.py'), 'replay', name, '--via', cli],
                                  text=True, capture_output=True, timeout=10, check=False)
            assert proc.returncode == 0, proc.stderr
            assert meta['cli_version'] in proc.stdout
            assert meta['model'] in proc.stdout and meta['effort'] in proc.stdout
