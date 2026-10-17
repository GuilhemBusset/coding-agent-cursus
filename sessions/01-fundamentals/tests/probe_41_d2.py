from pathlib import Path
import json
import subprocess
import sys
import tempfile


def test_recorded_repairs_really_fix_fresh_p00():
    demo = Path(__file__).resolve().parents[1] / 'cursus/demos/agent'
    with tempfile.TemporaryDirectory() as work:
        for cli in ['claude', 'codex']:
            reset = subprocess.run([sys.executable, str(demo / 'agent_demo.py'), 'reset', 'loop', '--work-root', work], capture_output=True, text=True)
            assert reset.returncode == 0, reset.stderr
            folder = Path(work) / 'loop'
            command = [str(folder / '.venv/bin/python'), '-m', 'pytest', '-q', 'test_p00_contract.py']
            red = subprocess.run(command, cwd=folder, text=True, capture_output=True)
            assert red.returncode == 1 and 'test_objective_contract' in red.stdout
            meta = json.loads((demo / f'recorded/loop-{cli}-run1.meta.json').read_text())
            (folder / 'p00_model.py').write_text(meta['post_state']['p00_model_py'])
            green = subprocess.run(command, cwd=folder, text=True, capture_output=True)
            assert green.returncode == 0, green.stdout + green.stderr
            changed = subprocess.check_output(['git', '-C', str(folder), 'diff', '--name-only'], text=True)
            assert changed.splitlines() == ['p00_model.py']
