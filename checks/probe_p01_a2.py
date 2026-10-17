"""Independent A2 agent-part probe: run and audit the promised benchmark harness."""
import json
import math
from pathlib import Path
import subprocess
import sys

session = Path(__file__).resolve().parents[1] / 'sessions/01-fundamentals'
result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-s', 'tests/instructor_p01_reference.py', '-k', 'laptop_benchmark'], cwd=session, capture_output=True, text=True, timeout=260)
assert result.returncode == 0, result.stdout + result.stderr
records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
assert len(records) == 1, result.stdout
record = records[0]
assert len(record['runs']) == 3 and record['reference_sha256'] and record['data_sha256']
for run in record['runs']:
    assert run['status'] == 'optimal' and run['raw_status'] == 'kOptimal' and run['checker_exit'] == 0, run
    assert math.isfinite(run['solve_seconds']) and run['solve_seconds'] < 60, run
    assert abs(run['primal'] - run['dual']) < 1e-5 and run['gap'] == 0, run
notes = (session / 'exercises/homework-p01/INSTRUCTOR.md').read_text(encoding='utf-8')
assert 'not proven' in notes and 'not a laptop measurement' in notes
assert 'test_laptop_benchmark' in notes and 'about 1/3' in notes
print(json.dumps({'desktop_harness_seconds': [r['solve_seconds'] for r in record['runs']], 'laptop_evidence': 'owner obligation'}))
