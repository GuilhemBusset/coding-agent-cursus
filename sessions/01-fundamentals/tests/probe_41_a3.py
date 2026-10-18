from pathlib import Path
import ast
import json
import subprocess
import sys


def test_open_solver_runs_original_instance():
    session = Path(__file__).resolve().parents[1]
    model = session / 'exercises/p00-lab/p00_model.py'
    proc = subprocess.run([sys.executable, str(model)], text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
    solution = json.loads(proc.stdout)
    assert solution['status'] == 'optimal' and abs(solution['objective'] - 485) < 1e-6
    forbidden = {'gurobipy', 'cplex', 'docplex', 'xpress', 'mosek', 'knitro', 'hexaly', 'coptpy'}
    sources = list((session / 'cursus/demos/agent').glob('*.py'))
    sources.append(session / 'exercises/p00-lab/p00_model.py')
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                assert not {n.name.split('.')[0] for n in node.names} & forbidden
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or '').split('.')[0] not in forbidden
