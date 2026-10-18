"""Independent D2 probe: replay real plans and reject named modelling mistakes."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile

pack = Path(__file__).resolve().parents[1] / 'sessions/01-fundamentals/exercises/homework-p01'
sys.path.insert(0, str(pack))
import p01_checker as checker
data = checker.load_data()
penalties = sum(t['penalty'] for t in data['trips'].values())
base = {'status': 'feasible', 'objective': penalties, 'assign': {}, 'cancel': {t: 1 for t in data['trips']}, 'charge': {}}
report = checker.check(base)
assert report.objective == penalties
assert {s.split(':')[0] for s in report.failures} == {'optimality'}, report
single = deepcopy(base)
single['assign'] = {'B001': {'T001': 1}}
single['cancel']['T001'] = 0
single['charge'] = {'B001': [{'slot': '21:00', 'charger': 'fast', 'kwh': 69}]}
# T001 uses 54 kWh, then D_E -> D_A uses 15 kWh and 34 minutes.
single['objective'] = penalties - data['trips']['T001']['penalty'] + 34 + 69 * (.15 + .04)
report = checker.check(single)
assert abs(report.objective - single['objective']) < 1e-6, report
assert {s.split(':')[0] for s in report.failures} == {'optimality'}, report
cases = {}
cases['objective'] = deepcopy(single)
cases['objective']['objective'] += 10
cases['integrality'] = deepcopy(single)
cases['integrality']['assign'] = {'B001': {'T001': .5}, 'B002': {'T001': .5}}
cases['charging-window'] = deepcopy(single)
cases['charging-window']['charge']['B001'][0]['slot'] = '05:00'
cases['charging-power'] = deepcopy(single)
cases['charging-power']['charge']['B001'][0]['kwh'] = 91
cases['soc'] = deepcopy(base)
cases['soc']['charge'] = {'B001': [{'slot': '00:00', 'charger': 'fast', 'kwh': 71}]}
cases['maintenance'] = deepcopy(base)
cases['maintenance']['charge'] = {'B009': [{'slot': '11:30', 'charger': 'fast', 'kwh': 1}]}
cases['charger-capacity'] = deepcopy(base)
cases['charger-capacity']['charge'] = {v: [{'slot': '21:00', 'charger': 'fast', 'kwh': 1}] for v in ('B001', 'B009')}
cases['coverage'] = deepcopy(base)
cases['coverage']['cancel']['T001'] = 0
for contract, solution in cases.items():
    failures = checker.check(solution).failures
    assert any(s.startswith(contract + ':') for s in failures), (contract, failures)
# Execute without site-packages: no highspy, pytest, numpy or model is available.
with tempfile.TemporaryDirectory() as temporary:
    path = Path(temporary) / 'plan.json'
    path.write_text(json.dumps(single), encoding='utf-8')
    result = subprocess.run([sys.executable, '-S', str(pack / 'p01_checker.py'), str(path)], capture_output=True, text=True)
    assert result.returncode == 1 and 'optimality:' in result.stdout and 'objective:' not in result.stdout, result.stdout + result.stderr
print('independent objective replay and eight named contracts passed')
