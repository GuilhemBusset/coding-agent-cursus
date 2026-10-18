"""Independent solver-free file replay and solve-contract collection."""
import csv
import json
from pathlib import Path
import re
import subprocess
import sys

PACK = Path(__file__).resolve().parents[1] / 'exercises/homework-p01'


def test_file_replay_recomputes_cost_and_names_errors(tmp_path):
    with (PACK / 'data/trips.csv').open(newline='') as stream:
        trips = list(csv.DictReader(stream))
    cost = sum(float(t['cancel_penalty']) for t in trips)
    solution = dict(status='feasible', objective=cost, assign={}, cancel={t['trip_id']:1 for t in trips}, charge={})
    path = tmp_path / 'plan.json'
    def check():
        path.write_text(json.dumps(solution), encoding='utf-8')
        r = subprocess.run([sys.executable, '-I', '-S', str(PACK / 'p01_checker.py'), str(path)], capture_output=True, text=True, timeout=10)
        assert 'Traceback' not in r.stderr, r.stderr
        return r, {line.partition(':')[0] for line in r.stdout.splitlines() if ':' in line and not line.startswith(' ')}
    result, tags = check()
    assert result.returncode == 1 and tags == {'optimality'}, result.stdout
    assert f'recomputed objective = {cost:.6f}' in result.stdout
    solution['objective'] = 0
    result, tags = check()
    assert 'objective' in tags and result.returncode == 1, result.stdout
    tid = trips[0]['trip_id']
    solution['objective'] = cost
    solution['cancel'][tid] = 0.5
    solution['assign'] = {'B001': {tid:0.5}}
    result, tags = check()
    assert result.returncode == 1 and 'integrality' in tags and 'coverage' not in tags, result.stdout
    solution['assign'] = {}
    solution['cancel'][tid] = 0
    result, tags = check()
    assert result.returncode == 1 and 'coverage' in tags, result.stdout
    result = subprocess.run([sys.executable, '-m', 'pytest', '--collect-only', '-q', str(PACK / 'p01_contract.py')], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    names = set(re.findall(r'::(test_\w+)', result.stdout))
    for tag in ('status','coverage','integrality','sequence','maintenance','charging_window','charging_power','charger_capacity','soc','objective','optimality'):
        assert f'test_{tag}_contract' in names
