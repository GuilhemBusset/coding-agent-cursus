"""Offline shape and relationship checks for the public v1 interfaces."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXED = Path(__file__).resolve().parents[2] / 'exercises' / 'fixed'
SCHEMAS = FIXED / 'schemas'
EXAMPLES = SCHEMAS / 'examples'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


POSITIVE = read(EXAMPLES / 'positive.json')
NEGATIVE = read(EXAMPLES / 'negative.json')
BY_NAME = {x['name']: x['value'] for x in POSITIVE}


class ContractError(ValueError):
    """A contract rejection returned from the session-local subprocess."""


def invoke(function, *args, **kwargs):
    # Run from the standalone session root, as the Python CLI/tools will do.
    # No import-path injection or repository runtime imports are needed.
    program = """import json, sys
from exercises.fixed.schemas import validate as contracts
request = json.load(sys.stdin)
try:
    value = getattr(contracts, request['function'])(*request['args'], **request['kwargs'])
except contracts.ContractError as exc:
    print(json.dumps({'error': str(exc)}))
else:
    print(json.dumps({'value': value}))
"""
    result = subprocess.run([sys.executable, '-c', program], cwd=FIXED.parents[1],
                            input=json.dumps(dict(function=function, args=args, kwargs=kwargs)),
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    response = json.loads(result.stdout)
    if 'error' in response:
        raise ContractError(response['error'])
    return response['value']


@pytest.mark.parametrize('example', POSITIVE, ids=lambda x: x['name'])
def test_positive_examples(example):
    invoke('validate', example['schema'], example['value'])


@pytest.mark.parametrize('example', NEGATIVE, ids=lambda x: x['name'])
def test_negative_examples(example):
    with pytest.raises(ContractError, match=example['error']):
        invoke('validate', example['schema'], example['value'])


def test_every_artifact_schema_has_positive_and_negative_examples():
    kinds = {p.name.removesuffix('.v1.schema.json') for p in SCHEMAS.glob('*.v1.schema.json')} - {'common'}
    assert {x['schema'] for x in POSITIVE} == kinds
    assert {x['schema'] for x in NEGATIVE} == kinds


# Runtime preparation/settings JSON is not an emitted v1 run-config artifact;
# its byte and operational checks live in test_run_boundary/test_run_accounting.
@pytest.mark.parametrize('path', sorted(
    path for path in (FIXED / 'config').glob('*.json')
    if '.snapshot.' in path.name or path.name.startswith(('policy.', 'run.illustrative.'))
), ids=lambda p: p.name)
def test_published_configuration(path):
    kind = 'snapshot' if '.snapshot.' in path.name else 'policy' if path.name.startswith('policy.') else 'run-config'
    invoke('validate', kind, read(path))


def bundle(case_id):
    return {kind: copy.deepcopy(BY_NAME[name + '-' + case_id]) for kind, name in [
        ('case', 'case'), ('reference', 'reference'), ('config', 'config'),
        ('claims', 'claims'), ('report', 'report'), ('scorecard', 'scorecard'),
    ]} | {
        'events': [json.loads(line) for line in (EXAMPLES / f'trace-{case_id}.jsonl').read_text().splitlines()],
        'markdown': (EXAMPLES / f'report-{case_id}.md').read_text(),
    }


@pytest.mark.parametrize('case_id', ['A', 'B', 'C'])
def test_linked_artifact_sets(case_id):
    invoke('validate_run', **bundle(case_id))


def test_failed_run_preserves_unknown_usage_and_honest_failure():
    failed = read(EXAMPLES / 'failed-run.json')
    invoke('validate_run', **failed)
    summary = invoke('summarize_scorecards', [failed['scorecard']])
    assert summary == dict(runs=1, successes=0, pass_rate=0, total_tokens=None,
                           tokens_per_success=None, efficiency_status='zero_success')


@pytest.mark.parametrize('target', ['claims', 'report', 'scorecard', 'events'])
def test_cross_artifact_run_identity_must_match(target):
    data = bundle('B')
    (data[target][0] if target == 'events' else data[target])['run_id'] = 'other-run'
    with pytest.raises(ContractError, match='identity'):
        invoke('validate_run', **data)


@pytest.mark.parametrize('field,value', [('attempt_id', 'missing-attempt'), ('request_id', 'other-request'), ('retry_of', 'missing-tool')])
def test_tool_invocations_require_registered_attempt_and_retry_identities(field, value):
    events = bundle('B')['events']
    events[3][field] = value
    with pytest.raises(ContractError, match='identity'):
        invoke('summarize_trace', events, 'run-B')


def test_model_retry_must_keep_logical_request_identity():
    events = bundle('B')['events']
    events[1]['request_id'] = 'other-request'
    with pytest.raises(ContractError, match='first attempt'):
        invoke('summarize_trace', events, 'run-B')


def test_report_anchor_references_do_not_depend_on_prose_wording():
    data = bundle('A')
    data['markdown'] = '\n'.join(f'<a id="{a["anchor"]}"></a>\nAlternative wording.' for a in data['report']['claim_anchors'])
    invoke('validate_run', **data)
    data['markdown'] = data['markdown'].replace('claim-methods', 'claim-absent')
    with pytest.raises(ContractError, match='anchor'):
        invoke('validate_run', **data)


def test_retries_failures_and_token_subsets_are_accounted_once():
    data = bundle('B')
    summary = invoke('summarize_trace', data['events'], 'run-B')
    assert summary['model_attempts'] == 2 and summary['logical_requests'] == 1
    assert summary['tool_invocations'] == 2 and summary['service_errors'] == 2
    # Failed outbound attempt: 100+20; retry: 200+40. Cache/reasoning are subsets.
    assert summary['usage']['cache_read_tokens'] == 20
    assert summary['usage']['reasoning_tokens'] == 10
    assert summary['total_tokens'] == 360
    failed = copy.deepcopy(read(EXAMPLES / 'failed-run.json')['scorecard'])
    failed['usage'] = dict(status='complete', input_tokens=1000, output_tokens=200,
                           cache_read_tokens=0, cache_write_tokens=0, reasoning_tokens=0)
    failed['total_tokens'] = 1200
    aggregate = invoke('summarize_scorecards', [data['scorecard'], failed])
    assert aggregate['runs'] == 2 and aggregate['successes'] == 1
    assert aggregate['pass_rate'] == 0.5 and aggregate['tokens_per_success'] == 1560
    assert invoke('summarize_scorecards', [failed])['tokens_per_success'] is None


def test_unknown_usage_contaminates_totals_and_efficiency_even_when_another_run_passes():
    failed = read(EXAMPLES / 'failed-run.json')
    accounting = invoke('summarize_trace', failed['events'], 'run-unknown')
    assert accounting['total_tokens'] is None and accounting['usage']['input_tokens'] is None
    aggregate = invoke('summarize_scorecards', [bundle('A')['scorecard'], failed['scorecard']])
    assert aggregate['successes'] == 1 and aggregate['total_tokens'] is None
    assert aggregate['tokens_per_success'] is None and aggregate['efficiency_status'] == 'unknown_usage'


def test_scorecard_cannot_drop_failed_attempt_or_award_itself_a_pass():
    data = bundle('B')
    data['scorecard']['model_attempts'] = 1
    with pytest.raises(ContractError, match='model_attempts'):
        invoke('validate_run', **data)
    data = read(EXAMPLES / 'failed-run.json')
    data['scorecard']['quality_pass'] = True
    with pytest.raises(ContractError, match='quality gate'):
        invoke('validate_run', **data)


def test_human_intervention_is_visible_and_prevents_quality_pass():
    data = bundle('A')
    end = data['events'].pop()
    data['events'].append(copy.deepcopy(BY_NAME['intervention']))
    end.update(sequence=2, elapsed_ms=200, intervention=True)
    data['events'].append(end)
    data['scorecard'].update(elapsed_ms=200, intervention=True, quality_pass=False)
    invoke('validate_run', **data)


def test_unsupported_schema_keywords_and_nonfinite_numbers_fail_explicitly():
    with pytest.raises(ContractError, match='unsupported schema keywords'):
        invoke('audit_schema', {'properties': {'x': {'format': 'email'}}})
    bad = copy.deepcopy(BY_NAME['reference-C'])
    bad['facts'][0]['assertion']['tolerance']['relative'] = float('nan')
    with pytest.raises(ContractError):
        invoke('validate', 'reference', bad)
