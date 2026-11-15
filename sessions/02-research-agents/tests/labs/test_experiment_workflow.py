"""Controlled experiments through the public CLI, real Pi, tools and grader; no API."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

SESSION = Path(__file__).resolve().parents[2]
EXAMPLES = SESSION / 'exercises/fixed/examples'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def journal(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def cli(module, *args, expected=0):
    result = subprocess.run([sys.executable, '-m', 'exercises.fixed.' + module, *map(str, args)],
                            cwd=SESSION, capture_output=True, text=True, timeout=120)
    print(result.stdout, result.stderr)
    assert result.returncode == expected, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope='module', autouse=True)
def runtime():
    result = subprocess.run(['node', '--version'], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == 'v24.15.0', 'use mise exec node@24.15.0 -- uv run --locked pytest ...'
    assert read(SESSION / 'node_modules/@earendil-works/pi-agent-core/package.json')['version'] == '1.5.2', 'run npm ci from the session lock first'


@pytest.fixture
def workspace():
    with TemporaryDirectory(prefix='s2-experiment-workflow-') as temporary:
        root = Path(temporary) / 'workspace with spaces'
        root.mkdir()
        try:
            yield root
        finally:
            for path in root.rglob('comparison.json'):
                result = read(path)
                print(path.name, json.dumps({k: result[k] for k in ('before', 'after', 'recommendation')}))


@pytest.mark.parametrize('kind,frozen,path', [
    ('harness', 'prompts', 'system.md'), ('prompt', 'harness', 'main.ts'),
])
def test_frozen_variable_violation_rejected(workspace, kind, frozen, path):
    spec = read(EXAMPLES / (kind + '.json'))
    baseline, candidate = workspace / 'baseline', workspace / 'candidate'
    cli('snapshot', '--exercises', EXAMPLES / spec['baseline'], '--output', baseline, '--name', 'before')
    working = workspace / 'working'
    cli('examples.workflow', 'rejoin', Path(spec['candidate']).name, '--exercises', working)
    target = working / frozen / path
    target.write_text(target.read_text(encoding='utf-8') + '\n// unintended frozen-variable edit\n', encoding='utf-8')
    # Newly saved, internally valid checksums: this exercises isolation, not corruption.
    cli('snapshot', '--exercises', working, '--output', candidate, '--name', 'after')
    assert read(baseline / 'snapshot.json')['files'][frozen] != read(candidate / 'snapshot.json')['files'][frozen]
    experiment = workspace / 'experiment.json'
    cli('examples.workflow', 'configure', kind, '--baseline', baseline, '--candidate', candidate, '--output', experiment)
    output = workspace / 'invalid'
    result = cli('evaluate', 'compare', '--experiment', experiment, '--output', output, expected=2)
    assert result['status'] == 'invalid_input'
    assert not (output / 'runs').exists()  # no paid or scripted attempt was launched


def check_controls(output, kind):
    shared = read(output / 'shared.json')
    public = read(SESSION / 'exercises/fixed/config/public/manifest.json')
    assert [{k: slot[k] for k in ('case_id', 'variant_id', 'seed', 'trial')} for slot in shared['schedule']] == public['schedule']['class']
    frozen = 'prompt' if kind == 'harness' else 'harness'
    for index, slot in enumerate(shared['schedule'], 1):
        before, after = [output / 'runs' / f'{role}-{index:02}' for role in ('baseline', 'candidate')]
        configs = [read(path / 'config.json') for path in (before, after)]
        for path, config in zip((before, after), configs):
            assert (path / 'shared.json').read_bytes() == (output / 'shared.json').read_bytes()
            assert all(config[k] == slot[k] for k in ('case_id', 'variant_id', 'seed', 'trial'))
            assert config['workspace']['fresh'] and config['evidence_kind'] == 'synthetic'
            assert read(path / 'scorecard.json')['total_tokens'] == read(path / 'accounting.json')['total_tokens']
            assert all((path / name).is_file() for name in ('trace.jsonl', 'claims.json', 'report.md', 'peer-review.md'))
        assert configs[0]['workspace']['workspace_id'] != configs[1]['workspace']['workspace_id']
        for key in ('model', 'settings', 'corpus', 'evaluator', 'rating_bundle', frozen):
            assert configs[0]['hashes'][key] == configs[1]['hashes'][key]
        assert configs[0]['hashes']['harness' if kind == 'harness' else 'prompt'] != configs[1]['hashes']['harness' if kind == 'harness' else 'prompt']


def test_completed_harness_quality_overrides_token_savings(workspace):
    output = workspace / 'harness'
    cli('evaluate', 'compare', '--experiment', EXAMPLES / 'harness.json', '--output', output, expected=1)
    result = read(output / 'comparison.json')
    check_controls(output, 'harness')
    before, after = result['before'], result['after']
    assert before['status'] == after['status'] == 'complete'
    assert before['quality_gates_pass'] and before['successes'] == 3
    assert not after['quality_gates_pass'] and after['successes'] == 0
    assert after['total_tokens'] < before['total_tokens']
    assert after['required_facts_met'] < before['required_facts_met']
    assert all(after['per_case'][case]['pass_rate'] < before['per_case'][case]['pass_rate'] for case in 'ABC')
    assert result['recommendation']['choice'] == 'revert'
    assert after['tokens_per_success'] is None and after['efficiency_status'] == 'zero_success'
    for role, summary in (('baseline', before), ('candidate', after)):
        traces = [journal(output / 'runs' / f'{role}-{i:02}/trace.jsonl') for i in range(1, 4)]
        assert sum(e['usage']['input_tokens'] + e['usage']['output_tokens'] for trace in traces for e in trace if e['type'] == 'model_attempt') == summary['total_tokens']
        assert all(trace[-1]['stop_reason'] == ('completed' if role == 'baseline' else 'no_progress') for trace in traces)
    calls = journal(output / 'runs/baseline-03/tool-results.jsonl')
    assert any(c['result']['tool'] == 'check_table' and c['result']['status'] == 'ok' for c in calls)
    calls = journal(output / 'runs/candidate-03/tool-results.jsonl')
    assert [c['result']['tool'] for c in calls] == ['read', 'search']


@pytest.mark.parametrize('name', ['prompt', 'paraphrases'])
def test_completed_frozen_code_prompt_comparisons(workspace, name):
    output = workspace / name
    cli('evaluate', 'compare', '--experiment', EXAMPLES / (name + '.json'), '--output', output, expected=1)
    check_controls(output, 'prompt')
    result = read(output / 'comparison.json')
    assert result['evidence_kind'] == result['evidence_status'] == 'synthetic'
    assert result['before']['quality_gates_pass'] and result['after']['quality_gates_pass']
    assert result['before']['total_tokens'] == result['after']['total_tokens']
    assert result['recommendation']['choice'] == 'revert'  # equal outcomes prove no gain
    assert result['peer_review']['status'] == 'pending'


def test_rejoin_preserves_work_and_restores_completed_snapshots(workspace):
    for source in sorted((EXAMPLES / 'versions').iterdir()):
        for group in ('harness', 'prompts'):
            (workspace / group).mkdir(exist_ok=True)
            (workspace / group / 'student-edit.txt').write_text(group + ' work', encoding='utf-8')
        result = cli('examples.workflow', 'rejoin', source.name, '--exercises', workspace)
        for group in ('harness', 'prompts'):
            assert (Path(result['backup']) / group / 'student-edit.txt').read_text(encoding='utf-8') == group + ' work'
            actual = {p.relative_to(workspace / group).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in (workspace / group).rglob('*') if p.is_file()}
            assert actual == read(source / 'snapshot.json')['files'][group]
