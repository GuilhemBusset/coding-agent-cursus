"""Offline saved-version comparisons, real boundary integration and independent arithmetic."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

SESSION = Path(__file__).resolve().parents[2]
FIXED = SESSION / 'exercises/fixed'
FIXTURES = FIXED / 'config/compare-fixtures'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n', encoding='utf-8')


def invoke(function, *args):
    # Like the other lab suites, import the standalone session package from a
    # subprocess working directory; do not alter Python's module search path.
    program = """
import json, sys
from pathlib import Path
from exercises.fixed import evaluate, snapshot
request = json.load(sys.stdin)
name, args = request['function'], request['args']
for index in {'compare': [0, 1], 'collect': [0], 'lines': [0], 'save': [0, 1]}.get(name, []):
    args[index] = Path(args[index])
module = snapshot if name == 'save' else evaluate
print(json.dumps(getattr(module, name)(*args)))
"""
    result = subprocess.run([sys.executable, '-c', program], cwd=SESSION,
                            input=json.dumps(dict(function=function, args=args), default=str),
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


class Evaluation:
    def __getattr__(self, name):
        return lambda *args: invoke(name, *args)


evaluate = Evaluation()


def save(*args):
    return invoke('save', *args)


def cli(*args):
    return subprocess.run([sys.executable, '-m', 'exercises.fixed.evaluate', *map(str, args)], cwd=SESSION,
                          capture_output=True, text=True, timeout=120)


@pytest.fixture
def scratch():
    with TemporaryDirectory(prefix='s2-compare-case-') as temporary:
        root = Path(temporary)
        try:
            yield root
        finally:
            for result in root.rglob('comparison.md'):
                print(str(result.relative_to(root)) + ':\n' + result.read_text(encoding='utf-8'))


@pytest.fixture(scope='session')
def installed():
    node = subprocess.run(['node', '--version'], capture_output=True, text=True, check=True)
    assert node.stdout.strip() == 'v24.15.0', 'run through mise exec node@24.15.0 -- uv run --locked pytest ...'
    if not (SESSION / 'node_modules/@earendil-works/pi-ai/package.json').exists():
        npm = shutil.which('npm')
        assert npm
        result = subprocess.run([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], cwd=SESSION,
                                capture_output=True, text=True, timeout=180)
        print(result.stdout, result.stderr)
        assert result.returncode == 0


def experiment(root, **changes):
    spec = read(FIXED / 'config/compare.scripted.v1.json')
    for key in ('settings', 'baseline', 'candidate', 'rating_export'):
        spec[key] = str((FIXED / 'config' / spec[key]).resolve())
    spec['scripts'] = {case: str((FIXED / 'config' / path).resolve()) for case, path in spec['scripts'].items()}
    spec.update(changes)
    path = root / 'experiment.json'
    write(path, spec)
    return path


@pytest.fixture(scope='session')
def comparison(installed):
    with TemporaryDirectory(prefix='s2-compare-tests-') as temporary:
        root = Path(temporary)
        spec = experiment(root)
        result = evaluate.compare(spec, root / 'output')
        print(json.dumps(dict(before=result['before'], after=result['after'], recommendation=result['recommendation'])))
        yield root / 'output', result


def test_shared_controls_and_artifacts(comparison):
    output, result = comparison
    assert result['exit_code'] == 0
    assert result['mode'] == 'class' and result['evidence_kind'] == 'synthetic'
    assert result['before']['quality_gates_pass'] and result['after']['quality_gates_pass']
    assert result['before']['total_tokens'] == 1080 and result['after']['total_tokens'] == 720
    shared = (output / 'shared.json').read_bytes()
    workspaces = set()
    for role in ('baseline', 'candidate'):
        assert read(output / 'versions' / role / 'snapshot.json')['snapshot_id'].startswith('scripted-')
        for index, slot in enumerate(read(output / 'shared.json')['schedule'], 1):
            path = output / 'runs' / f'{role}-{index:02}'
            assert (path / 'shared.json').read_bytes() == shared
            config = read(path / 'config.json')
            workspaces.add(config['workspace']['workspace_id'])
            assert all(config[k] == slot[k] for k in ('case_id', 'variant_id', 'seed', 'trial'))
            assert config['workspace']['fresh']
            assert all((path / name).is_file() for name in ('trace.jsonl', 'accounting.json', 'scorecard.json', 'report.md', 'peer-review.md', 'run-inputs.json'))
            # Both versions' first actual provider envelopes contain identical
            # prompt, case, tools and model controls, not just matching labels.
            if role == 'candidate':
                before = evaluate.lines(output / 'runs' / f'baseline-{index:02}' / 'requests.jsonl')[0]['body']
                assert evaluate.lines(path / 'requests.jsonl')[0]['body'] == before
    assert len(workspaces) == 6  # fixture harness also refuses carried file/module state
    assert all((output / name).is_file() for name in ('public-manifest.json', 'experiment.json', 'before.json', 'after.json', 'before.md', 'after.md', 'comparison.json', 'comparison.md'))


def test_saved_comparison_survives_working_edits(installed, scratch):
    versions = {}
    for role in ('baseline', 'candidate'):
        working = scratch / role
        shutil.copytree(FIXTURES / role, working)
        versions[role] = str(scratch / ('saved-' + role))
        save(working, Path(versions[role]), 'saved-' + role)
        (working / 'harness/main.ts').write_text('throw Error("edited working code")', encoding='utf-8')
        (working / 'prompts/research.md').write_text('edited working prompt', encoding='utf-8')
    result = evaluate.compare(experiment(scratch, **versions), scratch / 'output')
    assert result['exit_code'] == 0 and result['after']['successes'] == 3
    for role in versions:
        for index in range(1, 4):
            request = (scratch / 'output/runs' / f'{role}-{index:02}' / 'requests.jsonl').read_text(encoding='utf-8')
            assert 'edited working' not in request
    assert result['before']['tokens_per_success'] == 360 and result['after']['tokens_per_success'] == 240


def test_submission_and_failures_keep_every_slot(installed, scratch):
    # A scripted service error with missing usage stops each A run. B/C continue;
    # the three independent trials are never replaced by retries or dropped.
    script = scratch / 'service-error.json'
    write(script, [dict(throw=True)])
    spec = read(experiment(scratch, mode='submission'))
    spec['scripts']['A'] = str(script)
    bad_output = read(FIXTURES / 'C.json')
    # Preserve metering and tool use, but return a malformed research answer.
    for step in bad_output[1:]:
        events = [json.loads(s[6:]) for s in step['body'].splitlines() if s.startswith('data: ')]
        text = next(e['delta'] for e in events if e['type'] == 'response.output_text.delta')
        step['body'] = step['body'].replace(json.dumps(text), json.dumps('{}'))
    write(scratch / 'quality-error.json', bad_output)
    spec['scripts']['C'] = str(scratch / 'quality-error.json')
    write(scratch / 'experiment.json', spec)
    result = evaluate.compare(scratch / 'experiment.json', scratch / 'submission')
    assert result['exit_code'] == 1
    for role, key in [('baseline', 'before'), ('candidate', 'after')]:
        assert len(result['attempts'][role]) == 9
        score = result[key]
        assert score['scheduled'] == score['recorded'] == 9 and score['successes'] == 3
        assert score['per_case']['A'] == dict(scheduled=3, successes=0, pass_rate=0)
        assert score['stop_reasons']['service_error'] == 3
        assert score['stop_reasons']['invalid_output'] == 3
        assert score['service_errors'] == 3 and score['usage']['status'] == 'incomplete'
        assert score['total_tokens'] is None and score['tokens_per_success'] is None
        assert score['errors']
        for index, attempt in enumerate(result['attempts'][role], 1):
            config = read(scratch / 'submission/runs' / f'{role}-{index:02}' / 'config.json')
            assert config['mode'] == 'submission' and config['trial'] == attempt['slot']['trial']


def test_hand_calculated_aggregate():
    attempts = read(FIXTURES / 'aggregate.v1.json')
    for attempt in attempts:
        measured = evaluate.summarize_trace(attempt['trace'], attempt['run_id'])
        assert all(attempt['score'][k] == measured[k] for k in ('model_attempts', 'logical_requests', 'tool_invocations', 'service_errors', 'usage', 'total_tokens', 'elapsed_ms'))
    score = evaluate.aggregate(attempts)
    assert score['scheduled'] == 6 and score['successes'] == 4 and score['pass_rate'] == 4/6
    assert [score['per_case'][case]['pass_rate'] for case in 'ABC'] == [0.5, 1, 0.5]
    assert (score['model_attempts'], score['logical_requests'], score['tool_invocations'], score['service_errors']) == (7, 6, 8, 1)
    assert score['total_tokens'] == 1100 and score['tokens_per_success'] == 275
    assert score['usage'] == dict(status='complete', input_tokens=900, output_tokens=200, cache_read_tokens=70, cache_write_tokens=0, reasoning_tokens=20)
    assert score['required_facts_met'] == 54 and score['required_facts_total'] == 60 and score['fact_coverage'] == 0.9
    assert score['assertions']['citation'] == dict(total=6, passed=4)
    assert score['requirement_failures'] == {'decisive.A': 1, 'citation.A': 1, 'decisive.C': 1, 'citation.C': 1}
    assert score['elapsed_ms'] == 210 and score['stop_reasons'] == {'completed': 6}


def test_zero_success_and_incomplete_usage():
    attempts = read(FIXTURES / 'aggregate.v1.json')
    for attempt in attempts:
        attempt['score']['quality_pass'] = False
    score = evaluate.aggregate(attempts)
    assert score['tokens_per_success'] is None and score['efficiency_status'] == 'zero_success'
    assert evaluate.recommend(score, score)['machine_gates'] == 'fail'
    attempts = read(FIXTURES / 'aggregate.v1.json')
    attempts[0]['score']['usage']['cache_read_tokens'] = None
    attempts[0]['score']['usage']['status'] = 'partial'
    score = evaluate.aggregate(attempts)
    assert score['total_tokens'] == 1100 and score['tokens_per_success'] is None
    assert score['usage']['cache_read_tokens'] is None and score['known_usage_subtotals']['input_tokens'] == 900
    assert score['efficiency_status'] == 'incomplete_usage'


def quality(rates, tokens=100):
    return dict(status='complete', per_case={c: dict(pass_rate=r) for c,r in zip('ABC', rates)},
                successes=sum(rates), quality_gates_pass=all(r == 1 for r in rates), tokens_per_success=tokens,
                efficiency_status='available')


@pytest.mark.parametrize('before,after,choice', [
    (quality([1,1,1]), quality([1,1,0], 1), 'revert'),
    (quality([1,1,0]), quality([0,0,1], 1), 'revert'),
    (quality([1,1,1]), quality([1,1,1], 50), 'retain'),
    (quality([1,1,0]), quality([1,1,1]), 'retain'),
    (quality([1,1,1]), quality([2/3,1,1], 1), 'revert'),
    (quality([1,1,1]), dict(quality([1,1,1]), efficiency_status='incomplete_usage', tokens_per_success=None), 'insufficient_evidence'),
])
def test_quality_before_efficiency(before, after, choice):
    result = evaluate.recommend(before, after)
    assert result['choice'] == choice and result['reasons']
    assert result['status'] == 'provisional' and result['peer_review'] == 'pending'
    before['elapsed_ms'], after['elapsed_ms'] = 1, 99999999
    assert evaluate.recommend(before, after) == result


@pytest.mark.parametrize('defect,status,code', [('missing', 'missing', 1), ('hash', 'incompatible', 2), ('effective', 'incompatible', 2), ('settings', 'incompatible', 2)])
def test_missing_or_incompatible_attempts(comparison, scratch, defect, status, code):
    source, _ = comparison
    output = scratch / 'audit'
    shutil.copytree(source, output)
    attempt = output / 'runs/candidate-01'
    if defect == 'missing':
        (attempt / 'scorecard.json').unlink()
    elif defect == 'hash':
        config = read(attempt / 'config.json'); config['hashes']['corpus'] = '0'*64; write(attempt / 'config.json', config)
    elif defect == 'effective':
        measured = evaluate.lines(attempt / 'effective-settings.jsonl')
        measured[0]['settings']['max_output_tokens'] += 1
        (attempt / 'effective-settings.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in measured), encoding='utf-8')
    else:
        inputs = read(attempt / 'run-inputs.json'); inputs['settings']['budgets']['model_attempts'] += 1; write(attempt / 'run-inputs.json', inputs)
    result = evaluate.collect(output)
    assert result['exit_code'] == code and result['attempts']['candidate'][0]['status'] == status
    assert result['after']['scheduled'] == 3 and result['after']['per_case']['A']['pass_rate'] == 0
    assert result['recommendation']['choice'] == 'insufficient_evidence'
    assert result['after']['tokens_per_success'] is None
    assert result['peer_review']['status'] == 'pending' and result['evidence_status'] == 'synthetic'


@pytest.mark.parametrize('defect', ['missing_version', 'both_changed', 'settings'])
def test_invalid_version_inputs(installed, scratch, defect):
    spec_path = experiment(scratch)
    spec = read(spec_path)
    if defect == 'missing_version':
        saved = scratch / 'broken'
        shutil.copytree(FIXTURES / 'candidate', saved)
        metadata = read(saved / 'snapshot.json'); del metadata['snapshot_id']; write(saved / 'snapshot.json', metadata)
        spec['candidate'] = str(saved)
    elif defect == 'both_changed':
        working = scratch / 'working'; shutil.copytree(FIXTURES / 'candidate', working)
        (working / 'prompts/research.md').write_text('different prompt', encoding='utf-8')
        save(working, scratch / 'candidate', 'two-edits')
        spec['candidate'] = str(scratch / 'candidate')
    else:
        spec['candidate_settings'] = dict(model='another-model')
    write(spec_path, spec)
    result = cli('compare', '--experiment', spec_path, '--output', scratch / 'output')
    assert result.returncode == 2 and json.loads(result.stdout)['status'] == 'invalid_input'
    assert not (scratch / 'output/runs').exists()


def test_cli_status_and_pending_peer_review(comparison, scratch):
    source, original = comparison
    assert original['recommendation']['choice'] == 'retain'
    assert original['peer_review']['status'] == 'pending' and original['evidence_status'] == 'synthetic'
    output = scratch / 'cli'
    shutil.copytree(source, output)
    passed = cli('summarize', '--output', output)
    assert passed.returncode == 0 and json.loads(passed.stdout)['recommendation']['status'] == 'provisional'
    (output / 'runs/candidate-01/scorecard.json').unlink()
    failed = cli('summarize', '--output', output)
    assert failed.returncode == 1 and json.loads(failed.stdout)['recommendation']['choice'] == 'insufficient_evidence'
    invalid = cli('compare', '--experiment', FIXED / 'config/compare.scripted.v1.json', '--output', output)
    assert invalid.returncode == 2


def test_documented_compare_command(installed, scratch):
    output = scratch / 'compare-scripted'
    result = cli('compare', '--experiment', FIXED / 'config/compare.scripted.v1.json', '--output', output)
    print(result.stdout, result.stderr)
    assert result.returncode == 0
    saved = read(output / 'comparison.json')
    assert saved['before']['tokens_per_success'] == 360 and saved['after']['tokens_per_success'] == 240
    assert saved['recommendation']['choice'] == 'retain' and saved['peer_review']['status'] == 'pending'
    assert len(list((output / 'runs').glob('*/scorecard.json'))) == 6
    for name in ('before.json', 'after.json', 'comparison.md'):
        print(name + ':\n' + (output / name).read_text(encoding='utf-8'))
    assert all((output / name).is_file() for name in ('before.md', 'after.md', 'shared.json', 'versions/baseline/snapshot.json', 'versions/candidate/snapshot.json'))
