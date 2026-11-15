"""Rejoining must not delete the block instructions students are following."""

import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

SESSION = Path(__file__).resolve().parents[2]
EXERCISES = SESSION / 'exercises'


def documents():
    # Instruction files shipped in harness/ (prompts/*.md is model context, not documentation).
    return sorted(p.relative_to(EXERCISES).as_posix() for p in (EXERCISES / 'harness').rglob('*.md'))


@pytest.mark.parametrize('module,version', [
    ('checkpoint', '04-audit-stop'),
    ('examples.workflow', 'harness-baseline'),
    ('examples.workflow', 'prompt-vague'),
])
def test_rejoin_keeps_shipped_instructions(module, version):
    with TemporaryDirectory(prefix='s2-rejoin-docs-') as temporary:
        work = Path(temporary) / 'exercises'
        for group in ('harness', 'prompts'):
            shutil.copytree(EXERCISES / group, work / group)
        result = subprocess.run([sys.executable, '-m', 'exercises.fixed.' + module, 'rejoin', version,
                                 '--exercises', str(work)], cwd=SESSION, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        missing = [doc for doc in documents() if not (work / doc).is_file()]
        assert not missing, f'rejoin {version} removed block instructions from the working tree: {missing}'
