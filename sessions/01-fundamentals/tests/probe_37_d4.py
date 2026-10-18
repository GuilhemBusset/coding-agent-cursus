"""Exercise the public optimum API and verify reference custody."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

SESSION = Path(__file__).resolve().parents[1]
PACK = SESSION / 'exercises/homework-p01'

# Runs in the pack directory, so `import p01_checker` resolves beside it, as a student's run does.
API_SCRIPT = """import json, p01_checker as checker
data = checker.load_data()
penalties = sum(t['penalty'] for t in data['trips'].values())
solution = {'status':'feasible', 'objective':0, 'assign':{}, 'cancel':{tid:1 for tid in data['trips']}, 'charge':{}}
report = checker.check(solution, data)
print(json.dumps({'optimum': checker.KNOWN_OPTIMUM, 'penalties': penalties, 'objective': report.objective, 'failures': report.failures}))
"""


def test_committed_optimum_and_private_reference():
    api = subprocess.run([sys.executable, '-S', '-c', API_SCRIPT], cwd=PACK, capture_output=True, text=True, timeout=30)
    assert api.returncode == 0, api.stderr
    result = json.loads(api.stdout)
    assert math.isfinite(result['optimum']) and 0 < result['optimum'] < result['penalties']
    reference = Path(os.environ.get('P01_REFERENCE_DIR', '~/.local/share/coding-agent-cursus/instructor/s01-p01')).expanduser() / 'p01_model.py'
    root = SESSION.parents[1]
    assert not reference.resolve().is_relative_to(root)
    doc = (PACK / 'INSTRUCTOR.md').read_text()
    assert hashlib.sha256(reference.read_bytes()).hexdigest() in doc
    assert 'P01_REFERENCE_DIR' in doc and 'Release after the deadline' in doc
    tracked = subprocess.run(['git','ls-files','--','sessions/01-fundamentals'], cwd=root, capture_output=True, text=True, check=True).stdout.splitlines()
    for name in tracked:
        path = root / name
        if path.suffix == '.py':
            assert hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(reference.read_bytes()).digest(), 'private reference committed'
    assert result['objective'] == result['penalties']
    assert any(line.startswith('optimality:') for line in result['failures'])
