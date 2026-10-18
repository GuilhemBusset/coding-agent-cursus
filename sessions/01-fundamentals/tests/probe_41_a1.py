from pathlib import Path
import json
import hashlib
import subprocess
import sys
import tempfile


def test_two_resets_discard_prior_demo_work():
    demo = Path(__file__).resolve().parents[1] / 'cursus/demos/agent'
    with tempfile.TemporaryDirectory() as work:
        for name in ['loop', 'plan', 'bomb']:
            states = []
            for run in [1, 2]:
                reset = subprocess.run([sys.executable, str(demo / 'agent_demo.py'), 'reset', name, '--work-root', work], capture_output=True, text=True)
                assert reset.returncode == 0, reset.stderr
                folder = Path(work) / name
                assert not (folder / 'prior-run.txt').exists()
                if name == 'bomb':
                    assert [p.name for p in folder.iterdir()] == ['mcp.json']
                    states.append((folder / 'mcp.json').read_bytes())
                else:
                    assert '1 failed, 29 passed' in reset.stdout
                    files = subprocess.check_output(['git', '-C', str(folder), 'ls-files'], text=True).splitlines()
                    states.append({f: hashlib.sha256((folder / f).read_bytes()).hexdigest() for f in files})
                (folder / 'prior-run.txt').write_text('discard me')
            assert states[0] == states[1]
            for cli in ['claude', 'codex']:
                metas = [json.loads((demo / f'recorded/{name}-{cli}-run{r}.meta.json').read_text()) for r in [1, 2]]
                assert metas[0]['ended_at'] <= metas[1]['started_at']
                initial = [m['arms']['direct']['pre_state'] if name == 'plan' else m['pre_state'] for m in metas]
                assert initial[0]['file_hashes'] == initial[1]['file_hashes']
