"""Independent D3 probe: empty starter, documented schema and actual turn-in hook."""
import ast
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

session = Path(__file__).resolve().parents[1] / 'sessions/01-fundamentals'
pack = session / 'exercises/homework-p01'
sys.path.insert(0, str(pack))
import p01_model
try:
    p01_model.solve()
except NotImplementedError:
    pass
else:
    raise AssertionError('student starter must be empty')
readme = (pack / 'README.md').read_text(encoding='utf-8')
for token in ('Claude Code', 'Codex', 'build the model', 'checker', '"assign"', '"cancel"', '"charge"', '/turn-in 01', '$turn-in 01'):
    assert token in readme, token
with tempfile.TemporaryDirectory() as temporary:
    work = Path(temporary)
    shutil.copytree(session / 'exercises', work / 'exercises')
    hook = work / 'exercises/turn-in-check.sh'
    result = subprocess.run(['bash', str(hook)], cwd=work, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and 'WARNING' in result.stdout, result.stdout + result.stderr
    solution = work / 'exercises/homework-p01/solution.json'
    solution.write_text('{', encoding='utf-8')
    result = subprocess.run(['bash', str(hook)], cwd=work, capture_output=True, text=True, timeout=60)
    assert result.returncode != 0 and 'format:' in result.stdout, result.stdout + result.stderr
    # The executable stub must write solve()'s result next to itself.
    model = work / 'exercises/homework-p01/p01_model.py'
    tree = ast.parse(model.read_text(encoding='utf-8'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'solve')
    function.body = [ast.Return(ast.parse("{'status': 'no_solution'}", mode='eval').body)]
    model.write_text(ast.unparse(ast.fix_missing_locations(tree)), encoding='utf-8')
    # __main__ also prints the objective, so include the documented field.
    source = model.read_text(encoding='utf-8').replace("{'status': 'no_solution'}", "{'status': 'no_solution', 'objective': None}")
    model.write_text(source, encoding='utf-8')
    result = subprocess.run([sys.executable, str(model)], cwd=work, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(solution.read_text(encoding='utf-8')) == {'status': 'no_solution', 'objective': None}
print('empty starter and real turn-in hook passed')
