"""Checkpoint 04: real Pi/tools/grader with public synthetic provider scripts."""

import csv
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_contracts import invoke
from test_grading import artifacts, claim, grader_call, write
from test_memory_checkpoint import saved
from test_retrieval_checkpoints import (
    FIXED,
    SESSION,
    cli,
    dependencies,
    journal,
    load,
    response,
    student,
)

FINAL = FIXED / 'checkpoints/04-audit-stop'


def run(student, case='a-find', scenario=None, settings=None):
    args = ['--case', case, '--offline', '--exercises', student]
    if scenario:
        args += ['--scenario', scenario]
    if settings:
        args += ['--settings', settings]
    result = cli('checkpoint', 'run', '04-audit-stop', *args)
    print(json.dumps({k: result[k] for k in ('run_id', 'quality_pass', 'stop_reason', 'model_attempts', 'tool_invocations')}))
    return Path(result['output']), result


def consistent(output, reason):
    events = journal(output / 'trace.jsonl')
    score = load(output / 'scorecard.json')
    assert load(output / 'runtime-status.json')['stop_reason'] == score['stop_reason'] == reason
    assert events[-1]['type'] == 'run_end' and events[-1]['stop_reason'] == reason
    accounting = invoke('summarize_trace', events, score['run_id'])
    assert accounting == load(output / 'accounting.json')
    assert not accounting['intervention']
    dispatches = output / 'dispatches.jsonl'
    assert len(journal(dispatches) if dispatches.exists() else []) == accounting['model_attempts'] + accounting['tool_invocations']
    assert all((output / name).exists() for name in ('report.md', 'claims.json', 'report.json'))
    if reason != 'completed':
        assert not score['quality_pass'] and score['failed_assertion_ids']
        assert reason in (output / 'report.md').read_text()
    return accounting


def test_numerical_rows_and_required_uncertainty(student):
    cli('checkpoint', 'rejoin', '04-audit-stop', '--exercises', student)
    output, result = run(student, 'c-audit')
    assert result['quality_pass']
    consistent(output, 'completed')
    tool = next(e for e in journal(output / 'tool-results.jsonl') if e['result']['tool'] == 'check_table')
    data = tool['result']['data']
    with (SESSION / 'exercises/cases/c-audit/sources/EV-T01.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    selected = []
    for pair in data['pairs']:
        left, right = rows[pair['left_row'] - 1], rows[pair['right_row'] - 1]
        assert left['feasible'] == right['feasible'] == 'true'
        assert left['instance_id'] == right['instance_id'] and left['run_id'] == right['run_id']
        assert left['pair_id'] == right['pair_id'] == pair['pair_id']
        assert [int(left['cost']), int(right['cost'])] == [pair['left_value'], pair['right_value']]
        selected += [left, right]
    assert {r['row_id'] for r in selected} == {'EV-T01:R0001', 'EV-T01:R0002', 'EV-T01:R0003', 'EV-T01:R0004'}
    baseline = sum(int(r['cost']) for r in selected if r['method'] == 'audit-a')
    candidate = sum(int(r['cost']) for r in selected if r['method'] == 'audit-b')
    retained = load(output / 'candidate-output.json')['retained_evidence']['calculations'][0]
    assert retained['arguments'] == tool['invocation']['arguments']
    assert retained['pairs'] == data['pairs'] and retained['evidence'] == data['evidence']
    assert retained['denominator'] == retained['baseline_total'] == baseline == tool['audit']['denominator']
    assert retained['candidate_total'] == candidate
    assert retained['reduction_percent'] == 100 * (baseline - candidate) / baseline
    # The actual next model payload must contain those rows, not just an artifact.
    contexts = journal(output / 'memory-context.jsonl')
    assert contexts[-1]['memory'][0]['calculations'][0] == retained
    document = load(output / 'claims.json')
    assert claim(document, 'C-percent')['assertion']['value'] == retained['reduction_percent']
    assert any(c['kind'] == 'uncertainty' for c in document['claims'])
    # Correct arithmetic alone cannot pass either a false row citation or missing uncertainty.
    original = json.loads(json.dumps(document))
    claim(document, 'C-percent')['evidence'][0].update(start=5, end=7)
    artifacts(output, document)
    assert not grader_call('grade_run', str(output), str(SESSION / 'exercises/cases/c-audit'), str(output / 'policy.json'))['quality_pass']
    original['claims'] = [c for c in original['claims'] if c['kind'] != 'uncertainty']
    artifacts(output, original)
    assert not grader_call('grade_run', str(output), str(SESSION / 'exercises/cases/c-audit'), str(output / 'policy.json'))['quality_pass']


def test_recovery_continues_research_and_keeps_failed_invocation(student):
    cli('checkpoint', 'rejoin', '04-audit-stop', '--exercises', student)
    output, result = run(student, scenario='transient-read')
    assert result['quality_pass']
    accounting = consistent(output, 'completed')
    tools = [e for e in journal(output / 'trace.jsonl') if e['type'] == 'tool_invocation']
    spec = load(FIXED / 'config/public/faults/transient-read.json')
    assert tools[0]['result']['error'] == spec['responses'][0]['error']
    assert tools[1]['input']['arguments'] == tools[0]['input']['arguments']
    assert tools[1]['retry_of'] == tools[0]['tool_call_id'] and tools[1]['result']['status'] == 'ok'
    assert any(t['input']['tool'] == 'search' for t in tools[2:])
    assert len({t['input']['arguments'].get('source_id') for t in tools[2:]}) > 1
    assert accounting['service_errors'] == 1 and accounting['tool_invocations'] == len(tools)
    assert accounting['total_tokens'] == accounting['model_attempts'] * 120


@pytest.mark.parametrize(('scenario', 'reason', 'count'), [('repeated-retrieval', 'no_progress', 3), ('missing-source', 'service_error', 2)])
def test_partial_stops_on_no_progress_or_permanent_error(student, scenario, reason, count):
    cli('checkpoint', 'rejoin', '04-audit-stop', '--exercises', student)
    output, _ = run(student, scenario=scenario)
    accounting = consistent(output, reason)
    assert accounting['tool_invocations'] == count
    retained = load(output / 'candidate-output.json')['retained_evidence']['ledger']
    assert retained
    assert json.dumps(retained[0]['claim'], ensure_ascii=False) in (output / 'report.md').read_text()
    if scenario == 'missing-source':
        assert accounting['service_errors'] == 1


@pytest.mark.parametrize(('counter', 'limit', 'reason', 'models', 'tools'), [
    ('model_attempts', 1, 'model_budget', 1, 1),
    ('tool_invocations', 1, 'tool_budget', 2, 1),
    ('total_tokens', 1, 'token_budget', 0, 0),
])
def test_caps_block_dispatch_during_recovery(student, counter, limit, reason, models, tools):
    cli('checkpoint', 'rejoin', '04-audit-stop', '--exercises', student)
    settings = load(FIXED / 'config/run.v1.json')
    settings['budgets'][counter] = limit
    path = student / 'settings.json'
    write(path, settings)
    output, _ = run(student, scenario='transient-read', settings=path)
    accounting = consistent(output, reason)
    assert accounting['model_attempts'] == models and accounting['tool_invocations'] == tools
    if tools:
        assert accounting['service_errors'] == 1
    if counter == 'total_tokens':
        assert not journal(output / 'reservations.jsonl')[-1]['admitted']


def test_token_cap_retains_failure_before_denying_retry(student):
    cli('checkpoint', 'rejoin', '04-audit-stop', '--exercises', student)
    measured, _ = run(student, scenario='transient-read')
    reservation = journal(measured / 'reservations.jsonl')[0]['reserved_tokens']
    settings = load(FIXED / 'config/run.v1.json')
    settings['budgets']['total_tokens'] = reservation + 120
    path = student / 'token-cap.json'
    write(path, settings)
    output, _ = run(student, scenario='transient-read', settings=path)
    accounting = consistent(output, 'token_budget')
    assert accounting['model_attempts'] == accounting['tool_invocations'] == accounting['service_errors'] == 1
    assert accounting['total_tokens'] == 120
    reservations = journal(output / 'reservations.jsonl')
    assert reservations[0]['admitted'] and not reservations[-1]['admitted']


@pytest.mark.parametrize('text', ['{invalid', '{}', 'null', 'broken-anchor'])
def test_partial_invalid_output_is_not_completion(student, text):
    cli('checkpoint', 'rejoin', '04-audit-stop', '--exercises', student)
    snapshot = saved(student, 'invalid')
    cache = student / 'runs/cache'
    cli('run', 'prepare', '--cache', cache, '--export', FIXED / 'runtime/fixtures/rating-support.zip')
    script = student / 'invalid.json'
    final = response(2)
    # Replace the synthetic final text in every SSE event containing it.
    events = [json.loads(chunk[6:]) for chunk in final['body'].strip().split('\n\n')]
    original_text = next(e['delta'] for e in events if e['type'] == 'response.output_text.delta')
    if text == 'broken-anchor':
        value = json.loads(original_text)
        value['claim_anchors'][0]['anchor'] = 'claim-absent'
        text = json.dumps(value)
    final['body'] = final['body'].replace(json.dumps(original_text)[1:-1], json.dumps(text)[1:-1])
    write(script, [response(1, 'read', dict(source_id='EV-S01')), final])
    cli('run', 'run', '--snapshot', snapshot, '--exercises', student, '--cache', cache,
        '--script', script, '--tools', 'read,search', '--name', 'invalid')
    output = student / 'runs/invalid'
    consistent(output, 'invalid_output')
    candidate = load(output / 'candidate-output.json')
    assert candidate['validation_errors'] and candidate['retained_evidence']['ledger']
    assert candidate['validation_errors'][0] in (output / 'report.md').read_text()


def test_policy_repeated_retryable_failure_is_finite():
    # The public boundary injects exactly one error. Probe a second retryable
    # failure directly through the same student policy, without changing it.
    source = (FINAL / 'harness/policy.ts').as_uri()
    program = f"""
import {{ createPolicy }} from {json.dumps(source)};
const policy = createPolicy(); const args = {{ source_id: 'EV-S01', start: 0, end: 10 }};
const failure = {{ status: 'error', error: {{ code: 'service_error', retryable: true }} }};
policy.observe('read', args, failure, false);
const first = {{ reason: policy.reason, pending: policy.pending, admitted: policy.before('read', args) }};
policy.observe('read', args, failure, false);
console.log(JSON.stringify({{ first, reason: policy.reason, blocked: policy.before('read', args) }}));
"""
    result = subprocess.run(['node', '--input-type=module', '-'], cwd=SESSION, input=program,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['first']['pending'] and 'reason' not in value['first'] and 'admitted' not in value['first']
    assert value['reason'] == value['blocked'] == 'service_error'


def test_restore_and_abc_comparison_preserve_ab(student):
    cli('checkpoint', 'rejoin', '03-memory', '--exercises', student)
    # Correct C's absent-source pointer once, before freezing both versions.
    shutil.copyfile(FINAL / 'prompts/system.md', student / 'prompts/system.md')
    before = saved(student, 'before-stop')
    backup = cli('checkpoint', 'rejoin', '04-audit-stop', '--exercises', student)
    assert (Path(backup['backup']) / 'harness/main.ts').read_bytes() == (before / 'harness/main.ts').read_bytes()
    after = saved(student, 'with-stop')
    assert (before / 'prompts/system.md').read_bytes() == (after / 'prompts/system.md').read_bytes()
    result = cli('checkpoint', 'compare', '--audit-stop', '--baseline', before, '--candidate', after,
                 '--output', student / 'runs/abc')
    print(json.dumps(result))
    assert result['after']['C']['successes'] == 1
    for case in ('A', 'B'):
        assert result['before'][case]['successes'] == result['after'][case]['successes'] == 1
    shared = load(student / 'runs/abc/shared.json')
    assert len(shared['schedule']) == 3 and shared['evidence_kind'] == 'synthetic'
    for role in ('baseline', 'candidate'):
        for case in ('A', 'B', 'C'):
            output = student / 'runs/abc/runs' / (role + '-' + case)
            print(role, case, load(output / 'runtime-status.json'))
            assert not load(output / 'accounting.json')['intervention']
