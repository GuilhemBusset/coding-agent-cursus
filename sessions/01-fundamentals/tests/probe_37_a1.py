"""Actual instructor models, not hand-authored solutions, exercise the checker."""
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

PACK = Path(__file__).resolve().parents[1] / 'exercises/homework-p01'


def test_reference_and_two_modelling_mistakes(tmp_path):
    reference = Path(os.environ.get('P01_REFERENCE_DIR', '~/.local/share/coding-agent-cursus/instructor/s01-p01')).expanduser() / 'p01_model.py'
    source = reference.read_text(encoding='utf-8')
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VARIANT' for t in n.targets))
    for variant, tag in [('none',None), ('dropped-charging-window','charging-window'), ('relaxed-binary','integrality')]:
        directory = tmp_path / variant
        shutil.copytree(PACK, directory)
        lines = source.splitlines(keepends=True)
        lines[node.lineno-1:node.end_lineno] = [f'VARIANT = {variant!r}\n']
        (directory / 'p01_model.py').write_text(''.join(lines), encoding='utf-8')
        r = subprocess.run([sys.executable, '-c', "import json,p01_model; from pathlib import Path; Path('solution.json').write_text(json.dumps(p01_model.solve(time_limit=60)))"], cwd=directory, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr
        r = subprocess.run([sys.executable, '-I', '-S', str(directory / 'p01_checker.py')], capture_output=True, text=True, timeout=10)
        if tag is None:
            assert r.returncode == 0 and r.stdout.startswith('PASS'), r.stdout + r.stderr
            suite = subprocess.run([sys.executable, '-m', 'pytest', '-q', 'p01_contract.py'], cwd=directory, capture_output=True, text=True, timeout=120)
            assert suite.returncode == 0 and 'passed' in suite.stdout and 'skipped' not in suite.stdout, suite.stdout + suite.stderr
        else:
            assert r.returncode == 1 and any(line.startswith(tag+':') for line in r.stdout.splitlines()), r.stdout + r.stderr
            if tag == 'integrality':
                solution = json.loads((directory / 'solution.json').read_text())
                assert any(1e-6 < v < 1-1e-6 for assignments in solution['assign'].values() for v in assignments.values())
