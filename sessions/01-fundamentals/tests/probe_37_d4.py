"""Exercise the public optimum API and verify reference custody."""
import hashlib
import importlib.util
import math
import os
from pathlib import Path
import subprocess
import sys

SESSION = Path(__file__).resolve().parents[1]
PACK = SESSION / 'exercises/homework-p01'


def test_committed_optimum_and_private_reference():
    spec = importlib.util.spec_from_file_location('examiner_p01_checker', PACK / 'p01_checker.py')
    checker = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = checker
    spec.loader.exec_module(checker)
    data = checker.load_data()
    assert math.isfinite(checker.KNOWN_OPTIMUM) and 0 < checker.KNOWN_OPTIMUM < sum(t['penalty'] for t in data['trips'].values())
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
    solution = {'status':'feasible', 'objective':0, 'assign':{}, 'cancel':{tid:1 for tid in data['trips']}, 'charge':{}}
    report = checker.check(solution, data)
    assert report.objective == sum(t['penalty'] for t in data['trips'].values())
    assert any(line.startswith('optimality:') for line in report.failures)
