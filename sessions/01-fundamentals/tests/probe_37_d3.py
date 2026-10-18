"""Exercise the empty starter and the actual session hook in an isolated copy."""
from pathlib import Path
import shutil
import subprocess
import sys

SESSION = Path(__file__).resolve().parents[1]


def test_starter_and_turn_in_hook(tmp_path):
    pack = tmp_path / 'exercises/homework-p01'
    shutil.copytree(SESSION / 'exercises/homework-p01', pack)
    shutil.copyfile(SESSION / 'exercises/turn-in-check.sh', tmp_path / 'exercises/turn-in-check.sh')
    script = '''import p01_model as m
assert m.DATA_DIR.is_dir()
for call in (lambda:m.solve(),lambda:m.contract_status(None,False)):
    try: call()
    except NotImplementedError: pass
    else: raise AssertionError('starter must be empty')
'''
    r = subprocess.run([sys.executable, '-S', '-c', script], cwd=pack, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stderr
    hook = ['bash', 'exercises/turn-in-check.sh']
    r = subprocess.run(hook, cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and 'WARNING' in r.stdout and 'solution.json' in r.stdout, r.stdout + r.stderr
    (pack / 'solution.json').write_text('{', encoding='utf-8')
    r = subprocess.run(hook, cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and 'format:' in r.stdout, r.stdout + r.stderr
    readme = (pack / 'README.md').read_text()
    for entry in ('drive your agent to build the model', 'prove it with the checker', 'Claude Code', 'Codex', 'Solution format', '$turn-in 01', '/turn-in 01'):
        assert entry in readme
