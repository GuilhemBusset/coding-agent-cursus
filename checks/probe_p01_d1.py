"""Independent D1 probe: upstream derivation and real reference solve sizing."""
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
pack = root / 'sessions/01-fundamentals/exercises/homework-p01'
upstream = root / 'sessions/01-fundamentals/tests/fixtures/p01_upstream'
def rows(path):
    with path.open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))
original = {r['trip_id']: r for r in rows(upstream / 'data/trips.csv')}
revised = rows(pack / 'data/trips.csv')
assert len(revised) == 40 and all(r == original[r['trip_id']] for r in revised)
original_vehicles = {r['vehicle_id']: r for r in rows(upstream / 'data/vehicles.csv')}
vehicles = rows(pack / 'data/vehicles.csv')
assert len(vehicles) == 10
assert all(float(v['max_soc_kwh']) < float(original_vehicles[v['vehicle_id']]['max_soc_kwh']) for v in vehicles)
assert all(float(v['initial_soc_kwh']) < float(original_vehicles[v['vehicle_id']]['initial_soc_kwh']) for v in vehicles)
reference = Path(os.environ.get('P01_REFERENCE_DIR', '~/.local/share/coding-agent-cursus/instructor/s01-p01')).expanduser() / 'p01_model.py'
driver = '''
import json, highspy, p01_model
original = highspy.Highs.run
observed = []
def run(self, *args, **kwargs):
    answer = original(self, *args, **kwargs)
    info = self.getInfo()
    observed.append([self.getModelStatus().name, self.getRunTime(), info.objective_function_value, info.mip_dual_bound, info.mip_gap])
    return answer
highspy.Highs.run = run
solution = p01_model.solve(time_limit=60)
assert observed and observed[-1][0] == 'kOptimal', observed
assert 5 <= observed[-1][1] < 60, observed
assert abs(observed[-1][2] - observed[-1][3]) < 1e-5 and observed[-1][4] == 0
open('solution.json', 'w').write(json.dumps(solution))
print(json.dumps(observed))
'''
with tempfile.TemporaryDirectory() as temporary:
    work = Path(temporary) / 'pack'
    shutil.copytree(pack, work)
    shutil.copyfile(reference, work / 'p01_model.py')
    result = subprocess.run([sys.executable, '-c', driver], cwd=work, capture_output=True, text=True, timeout=100)
    assert result.returncode == 0, result.stdout + result.stderr
    checked = subprocess.run([sys.executable, '-S', 'p01_checker.py'], cwd=work, capture_output=True, text=True)
    assert checked.returncode == 0 and checked.stdout.startswith('PASS'), checked.stdout + checked.stderr
    print(result.stdout.strip())
