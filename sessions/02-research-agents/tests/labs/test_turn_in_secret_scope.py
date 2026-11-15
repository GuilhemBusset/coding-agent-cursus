"""Secret hygiene covers every exercises/ file that the shared turn-in would commit (D3)."""

import json
import shutil
from pathlib import Path

import pytest
from test_standalone import offline
from test_turn_in import complete  # noqa: F401  (reuse the truthful complete fixture)

KEY = 'sk-' + 'testCredential1234567890' * 2


@pytest.mark.parametrize('relative', ['scratch/creds.txt', 'harness-notes/env.md'])
def test_credential_in_any_submitted_subfolder_is_rejected(complete, tmp_path, relative):  # noqa: F811
    exercises = tmp_path / 'exercises'
    shutil.copytree(complete, exercises)
    target = exercises / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('OPENAI_API_KEY=' + KEY + '\n', encoding='utf-8')
    result = offline('turn_in_check', '--exercises', exercises, '--seal', codes=(0, 1))
    assert not json.loads(result.stdout)['accepted']
    assert 'testCredential' not in result.stdout
    assert Path(target).is_file()
