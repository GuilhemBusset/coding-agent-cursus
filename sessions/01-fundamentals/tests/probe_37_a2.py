"""Validate the delivered owner benchmark; do not attest laptop hardware."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

SESSION = Path(__file__).resolve().parents[1]
PACK = SESSION / 'exercises/homework-p01'


def test_owner_benchmark_produces_pinned_evidence():
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-s', 'tests/instructor_p01_reference.py', '-k', 'laptop_benchmark'], cwd=SESSION, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
    assert len(evidence) == 1
    evidence = evidence[0]
    reference = Path(os.environ.get('P01_REFERENCE_DIR', '~/.local/share/coding-agent-cursus/instructor/s01-p01')).expanduser() / 'p01_model.py'
    assert evidence['reference_sha256'] == hashlib.sha256(reference.read_bytes()).hexdigest()
    assert evidence['data_sha256'] == {p.name:hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in (PACK/'data').glob('*.csv')}
    assert evidence['host'] and evidence['highs_version'] and evidence['checkout_revision']
    assert len(evidence['runs']) == 3
    for run in evidence['runs']:
        assert run['raw_status'] == 'kOptimal' and run['checker_exit'] == 0
        assert run['options'] == {'threads':1, 'mip_rel_gap':0.0}
        assert 0 < run['solve_seconds'] < 60 and run['gap'] == 0
        assert abs(run['primal'] - run['dual']) < 1e-5
    doc = (PACK/'INSTRUCTOR.md').read_text()
    assert '**Status: not proven.**' in doc and 'not a laptop measurement' in doc
