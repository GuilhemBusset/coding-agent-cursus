"""Independent A1 probe: solve the private model and two genuine mistake variants."""
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

pack = Path(__file__).resolve().parents[1] / 'sessions/01-fundamentals/exercises/homework-p01'
private = Path(os.environ.get('P01_REFERENCE_DIR', '~/.local/share/coding-agent-cursus/instructor/s01-p01')).expanduser() / 'p01_model.py'
source = private.read_text(encoding='utf-8')
assignment = next(n for n in ast.parse(source).body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VARIANT' for t in n.targets))
with tempfile.TemporaryDirectory() as temporary:
    objectives = {}
    for variant, expected in [('none', None), ('dropped-charging-window', 'charging-window'), ('relaxed-binary', 'integrality'), ('dropped-charger-capacity', 'charger-capacity')]:
        work = Path(temporary) / variant
        shutil.copytree(pack, work)
        lines = source.splitlines(keepends=True)
        lines[assignment.lineno - 1:assignment.end_lineno] = [f'VARIANT = {variant!r}\n']
        (work / 'p01_model.py').write_text(''.join(lines), encoding='utf-8')
        solved = subprocess.run([sys.executable, 'p01_model.py'], cwd=work, capture_output=True, text=True, timeout=150)
        assert solved.returncode == 0, solved.stdout + solved.stderr
        solution = json.loads((work / 'solution.json').read_text(encoding='utf-8'))
        objectives[variant] = solution['objective']
        checked = subprocess.run([sys.executable, '-S', 'p01_checker.py'], cwd=work, capture_output=True, text=True)
        if expected is None:
            assert checked.returncode == 0 and checked.stdout.startswith('PASS'), checked.stdout + checked.stderr
            contracts = subprocess.run([sys.executable, '-m', 'pytest', '-q', 'p01_contract.py'], cwd=work, capture_output=True, text=True, timeout=150)
            assert contracts.returncode == 0 and 'passed' in contracts.stdout, contracts.stdout + contracts.stderr
        else:
            assert checked.returncode == 1, checked.stdout + checked.stderr
            assert any(line.startswith(expected + ':') for line in checked.stdout.splitlines()), checked.stdout
            assert solution['objective'] < objectives['none'], objectives
    print(json.dumps(objectives, sort_keys=True))
