"""Independent expected totals and dispatch spies at enforced boundaries."""

import json

import pytest
from test_run_boundary import (  # fixtures are shared by both integration suites
    installed,
    lab,
    launch,
    load,
    response,
    snapshot,
    trace,
    usage,
)


def records(out, name):
    path = out / name
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


def test_independent_request_and_tool_accounting(lab):
    saved = snapshot(lab, '''export async function run(api) {
  await api.model(); await api.tools(); await api.model(); api.intervention('steer');
}''')
    out, status = launch(lab, saved, [response(tokens=usage(10, 2, 1, 1), failed=True),
        response([('search', dict(query='charger', limit=1)), ('read', dict(source_id='missing', start=0, end=100))]),
        response(tokens=usage(30, 6, 3, 1))])
    events = trace(out)
    attempts = [e for e in events if e['type'] == 'model_attempt']
    assert [(e['request_id'], e['attempt_id'], e['retry_of'], e['status']) for e in attempts] == [
        ('request-1', 'attempt-1', None, 'error'), ('request-1', 'attempt-2', 'attempt-1', 'ok'),
        ('request-2', 'attempt-3', None, 'ok')]
    tools = [e for e in events if e['type'] == 'tool_invocation']
    assert len(tools) == 2 and [e['result']['status'] for e in tools] == ['ok', 'error']
    assert len(records(out, 'requests.jsonl')) == 3
    assert [e['type'] for e in records(out, 'dispatches.jsonl')] == ['model', 'model', 'tool', 'tool', 'model']
    summary = load(out / 'accounting.json')
    assert summary['model_attempts'] == 3 and summary['logical_requests'] == 2
    assert summary['tool_invocations'] == 2 and summary['service_errors'] == 2
    assert summary['total_tokens'] == 168  # 12 + 120 + 36; cached/reasoning are SUBSETS
    assert summary['usage'] == dict(status='complete', input_tokens=140, output_tokens=28,
                                   cache_read_tokens=14, cache_write_tokens=0, reasoning_tokens=4)
    assert summary['intervention'] and status['intervention'] and summary['elapsed_ms'] > 0
    assert load(out / 'scorecard.json')['model_attempts'] == 3
    reservations = records(out, 'reservations.jsonl')
    assert len(reservations) == 3 and reservations[1]['observed_tokens_before'] == 12
    assert all(r['reserved_tokens'] > 120 for r in reservations)
    assert 'reserved_tokens' not in summary['usage']


@pytest.mark.parametrize('cap,limit,expected,dispatches', [
    ('model_attempts', 1, 'model_budget', ['model', 'tool', 'tool']),
    ('tool_invocations', 1, 'tool_budget', ['model', 'tool']),
    ('total_tokens', 1, 'token_budget', []),
])
def test_caps_prevent_dispatch(lab, cap, limit, expected, dispatches):
    options = dict(lab['options'], budgets=dict(lab['options']['budgets'], **{cap: limit}))
    saved = snapshot(lab, '''export async function run(api) {
  await api.model(); await api.tools(); await api.model();
}''')
    out, status = launch(lab, saved, [response([('search', dict(query='charger')), ('read', dict(source_id='EV-S01'))]), response()], options=options)
    assert status['detail'] == status['stop_reason'] == expected
    assert [d['type'] for d in records(out, 'dispatches.jsonl')] == dispatches
    assert [e['type'] for e in trace(out)].count('tool_invocation') == dispatches.count('tool')
    assert (out / 'claims.json').is_file() and (out / 'report.json').is_file() and (out / 'scorecard.json').is_file()
    assert trace(out)[-1]['stop_reason'] == expected
    if cap == 'total_tokens':
        reservation = records(out, 'reservations.jsonl')[0]
        assert not reservation['admitted'] and load(out / 'accounting.json')['total_tokens'] == 0
    if cap == 'model_attempts':
        assert [e['result']['status'] for e in trace(out) if e['type'] == 'tool_invocation'] == ['ok', 'ok']


def test_candidate_pass_flags_and_counters_are_not_ratings(lab):
    saved = snapshot(lab, '''export async function run(api) {
  await api.model(); return { quality_pass: true, model_attempts: 0, total_tokens: 0,
    claims: [], claim_anchors: [], markdown: 'unsupported answer' };
}''')
    out, status = launch(lab, saved, [response()])
    score = load(out / 'scorecard.json')
    assert not score['quality_pass'] and not score['output_valid']
    assert score['model_attempts'] == 1 and score['total_tokens'] == 120
    assert status['detail'] == 'invalid_output'
    assert load(out / 'candidate-output.json')['quality_pass'] is True


@pytest.mark.parametrize('scenario,detail,count', [
    ('unknown-model', 'reservation_unknown', 0),
    ('malformed-tool', 'invalid_tool_request', 1),
])
def test_unsupported_work_is_refused_before_dispatch(lab, scenario, detail, count):
    options = json.loads(json.dumps(lab['options']))
    if scenario == 'unknown-model':
        options['connection'].update(provider='openai-compatible', model='unknown-tokenizer')
    saved = snapshot(lab, 'export async function run(api) { await api.model(); await api.tools(); }')
    out, status = launch(lab, saved, [response([('search', dict(unexpected='invalid'))])], options=options)
    assert status['detail'] == detail
    assert len(records(out, 'requests.jsonl')) == count
    assert load(out / 'accounting.json')['tool_invocations'] == 0


@pytest.mark.parametrize('scenario,detail,attempts', [
    ('unknown', 'accounting_unknown', 1), ('network', 'accounting_unknown', 1),
    ('timeout', 'accounting_unknown', 1), ('cancelled', 'cancelled', 1),
    ('pre-cancelled', 'cancelled', 0), ('retry-model-cap', 'model_budget', 1),
    ('retry-token-cap', 'token_budget', 1), ('run-timeout', 'run_timeout', 0),
])
def test_unknown_usage_retry_reservations_and_cancellation(lab, scenario, detail, attempts):
    options = json.loads(json.dumps(lab['options']))
    source = 'export async function run(api) { try { await api.model(); } catch {} await api.model(); }'
    steps = [response(tokens=None), response()]
    if scenario == 'network':
        steps = [dict(throw=True), response()]
    if scenario in ('timeout', 'cancelled'):
        steps = [dict(stall=True), response()]
        options['connection']['timeout_ms'] = 30 if scenario == 'timeout' else 500
        if scenario == 'cancelled':
            source = 'export async function run(api) { setTimeout(() => api.cancel(), 30); await api.model(); }'
    if scenario == 'pre-cancelled':
        source = 'export async function run(api) { api.cancel(); await api.model(); }'
    if scenario.startswith('retry-'):
        # Known failure usage permits a retry, which must pass fresh admission.
        steps = [response(tokens=usage(6000, 1000), failed=True), response()]
        if scenario == 'retry-model-cap':
            options['budgets']['model_attempts'] = 1
        else:
            # Learn the complete envelope reservation from an independent first
            # run. Set enough headroom for that request, but not its retry after
            # reconciling 7,000 observed tokens. No candidate estimate is used.
            probe = snapshot(lab, source, 'probe')
            probe_out, _ = launch(lab, probe, [response()], 'reservation-probe')
            bound = records(probe_out, 'reservations.jsonl')[0]['reserved_tokens']
            options['budgets']['total_tokens'] = bound
    if scenario == 'run-timeout':
        options['run_timeout_ms'] = 30
        source = 'export async function run(api) { await new Promise(() => {}); }'
    saved = snapshot(lab, source)
    out, status = launch(lab, saved, steps, options=options)
    assert status['detail'] == detail
    assert len(records(out, 'requests.jsonl')) == attempts
    assert len([e for e in trace(out) if e['type'] == 'model_attempt']) == attempts
    assert (out / 'report.md').is_file() and (out / 'config.json').is_file()
    accounting = load(out / 'accounting.json')
    if scenario == 'run-timeout':
        assert accounting['elapsed_ms'] >= options['run_timeout_ms']
    if scenario in ('unknown', 'network', 'timeout', 'cancelled'):
        assert accounting['total_tokens'] is None
        assert trace(out)[0]['usage']['input_tokens'] is None
    if scenario in ('timeout', 'cancelled'):
        assert trace(out)[0]['status'] == 'cancelled'
        assert trace(out)[0]['error']['code'] == ('timeout' if scenario == 'timeout' else 'cancelled')
    if scenario == 'retry-token-cap':
        reservations = records(out, 'reservations.jsonl')
        assert len(reservations) == 2 and not reservations[1]['admitted']
        assert reservations[1]['observed_tokens_before'] == 7000
        assert accounting['total_tokens'] == 7000
