"""Independent D4 probe: fixed optimum and an external, documented private model."""
import ast
import hashlib
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
pack = root / 'sessions/01-fundamentals/exercises/homework-p01'
tree = ast.parse((pack / 'p01_checker.py').read_text(encoding='utf-8'))
values = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'KNOWN_OPTIMUM' for t in n.targets)]
assert len(values) == 1 and 0 < values[0] < 108520, values
private = Path(os.environ.get('P01_REFERENCE_DIR', '~/.local/share/coding-agent-cursus/instructor/s01-p01')).expanduser() / 'p01_model.py'
assert private.is_file() and not private.resolve().is_relative_to(root.resolve())
notes = (pack / 'INSTRUCTOR.md').read_text(encoding='utf-8')
assert '.local/share/coding-agent-cursus/instructor/s01-p01/p01_model.py' in notes
assert hashlib.sha256(private.read_bytes()).hexdigest() in notes
tracked = subprocess.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True, check=True).stdout.split(b'\0')
private_source = private.read_bytes()
assert all((root / os.fsdecode(name)).read_bytes() != private_source for name in tracked if name and (root / os.fsdecode(name)).is_file())
for model in pack.rglob('p01_model.py'):
    assert 'NotImplementedError' in model.read_text(encoding='utf-8')
assert not list(pack.rglob('solution.json'))
print('committed optimum', values[0], '; private reference remains external')
