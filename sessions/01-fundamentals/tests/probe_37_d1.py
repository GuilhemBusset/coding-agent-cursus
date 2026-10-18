"""Independent D1 measurement and binding probe; private artifacts stay temporary."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

SESSION = Path(__file__).resolve().parents[1]
PACK = SESSION / 'exercises/homework-p01'


def test_port_binding_and_fresh_solve_time(tmp_path):
    reference = Path(os.environ.get('P01_REFERENCE_DIR', '~/.local/share/coding-agent-cursus/instructor/s01-p01')).expanduser() / 'p01_model.py'
    source = reference.read_text(encoding='utf-8')
    assert hashlib.sha256(reference.read_bytes()).hexdigest() in (PACK / 'INSTRUCTOR.md').read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VARIANT' for t in n.targets))
    driver = '''import json, highspy
from pathlib import Path
observed=[]
original=highspy.Highs.run
def run(self,*a,**kw):
    r=original(self,*a,**kw)
    i=self.getInfo()
    observed.append([self.getModelStatus().name,self.getRunTime(),i.objective_function_value,i.mip_dual_bound,i.mip_gap])
    return r
highspy.Highs.run=run
import p01_model
s=p01_model.solve(time_limit=60)
Path('solution.json').write_text(json.dumps(s))
Path('observed.json').write_text(json.dumps(observed))
'''
    results = {}
    for index, variant in enumerate(['none', 'none', 'none', 'dropped-charger-capacity', 'dropped-charging-window']):
        directory = tmp_path / str(index)
        shutil.copytree(PACK, directory)
        lines = source.splitlines(keepends=True)
        lines[node.lineno-1:node.end_lineno] = [f'VARIANT = {variant!r}\n']
        (directory / 'p01_model.py').write_text(''.join(lines), encoding='utf-8')
        solved = subprocess.run([sys.executable, '-c', driver], cwd=directory, text=True, capture_output=True, timeout=120)
        assert solved.returncode == 0, solved.stderr
        observed = json.loads((directory / 'observed.json').read_text())[-1]
        checked = subprocess.run([sys.executable, '-I', '-S', str(directory / 'p01_checker.py')], text=True, capture_output=True, timeout=20)
        if variant == 'none':
            assert observed[0] == 'kOptimal' and abs(observed[2] - observed[3]) < 1e-5 and observed[4] == 0
            assert 5 <= observed[1] < 60
            assert checked.returncode == 0 and checked.stdout.startswith('PASS'), checked.stdout
            results['none'] = observed[2]
        else:
            tag = {'dropped-charger-capacity':'charger-capacity', 'dropped-charging-window':'charging-window'}[variant]
            tags = {line.partition(':')[0] for line in checked.stdout.splitlines() if ':' in line and not line.startswith(' ')}
            assert checked.returncode == 1 and tags == {tag}, checked.stdout
            assert observed[2] < results['none'] - 1e-4
