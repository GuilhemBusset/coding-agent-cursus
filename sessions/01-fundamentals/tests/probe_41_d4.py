from pathlib import Path
import hashlib
import json


def test_same_task_plan_is_readonly_and_supplied_to_build():
    demo = Path(__file__).resolve().parents[1] / 'cursus/demos/agent'
    paths = sorted((demo / 'recorded').glob('plan-*.meta.json'))
    assert {p.name for p in paths} == {f'plan-{cli}-run{r}.meta.json' for cli in ['claude', 'codex'] for r in [1, 2]}
    for path in paths:
        meta = json.loads(path.read_text())
        direct, plan, build = [meta['arms'][a] for a in ['direct', 'plan', 'build']]
        digest = hashlib.sha256(direct['prompt'].encode()).hexdigest()
        assert direct['prompt_sha256'] == digest == meta['task_prompt_sha256']
        assert plan['prompt'].startswith('Plan only.') and plan['prompt'].endswith(direct['prompt'])
        assert plan['pre_state']['file_hashes'] == plan['post_state']['file_hashes']
        assert direct['pre_state']['file_hashes'] == plan['pre_state']['file_hashes']
        assert plan['post_state']['file_hashes'] == build['pre_state']['file_hashes']
        assert plan['plan_text'] and plan['plan_text'] in build['prompt']
        assert build['prompt'].endswith(direct['prompt'])
        for arm in [direct, build]:
            assert arm['post_state']['pytest_exit_code'] == 0
