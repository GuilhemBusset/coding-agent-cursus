"""Offline grading behaviour: actual assertions, support, accounting and CLI."""

import copy
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from test_contracts import ContractError, invoke

SESSION = Path(__file__).resolve().parents[2]

FIXED = SESSION / 'exercises/fixed'
CASES = SESSION / 'exercises/cases'
FIXTURES = FIXED / 'grading/fixtures'
POLICY = FIXED / 'config/policy.v1.json'
MANIFEST = json.loads((FIXTURES / 'manifest.json').read_text())


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def grader_call(function, *args):
    program = '''import json, sys
from pathlib import Path
from exercises.fixed.grading import engine
request = json.load(sys.stdin)
try:
    args = request['args']
    if request['function'] == 'grade_run': args = [Path(a) for a in args]
    value = getattr(engine, request['function'])(*args)
except ValueError as exc:
    print(json.dumps({'error': str(exc)}))
else:
    print(json.dumps({'value': value}))
'''
    result = subprocess.run([sys.executable, '-c', program], cwd=SESSION,
                            input=json.dumps(dict(function=function, args=args)), capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    response = json.loads(result.stdout)
    if 'error' in response:
        raise ContractError(response['error'])
    return response['value']


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def artifacts(run, document, prose=None):
    """Publish test research output with its report anchors, without grading it."""
    write(run / 'claims.json', document)
    report = {k: document[k] for k in ('schema_version', 'run_id', 'case_id', 'variant_id')}
    report.update(claims_path='claims.json', report_path='report.md', claim_anchors=[
        dict(claim_id=c['claim_id'], anchor='claim-' + c['claim_id']) for c in document['claims']])
    write(run / 'report.json', report)
    (run / 'report.md').write_text('\n\n'.join(
        f'<a id="{a["anchor"]}"></a>\n{prose or a["claim_id"] + " is asserted here."}'
        for a in report['claim_anchors']), encoding='utf-8')


def prepare(tmp_path, name='pass-C'):
    run = tmp_path / name
    shutil.copytree(FIXTURES / name, run)
    entry = next(x for x in MANIFEST if x['name'] == name)
    return run, CASES / entry['case']


def grade(run, case):
    return grader_call('grade_run', str(run), str(case), str(POLICY))


def claim(document, fact_id):
    return next(c for c in document['claims'] if fact_id in c['reference_fact_ids'])


def trace_write(run, events):
    for i, event in enumerate(events):
        event['sequence'] = i
    (run / 'trace.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')


def events_read(run):
    return [json.loads(line) for line in (run / 'trace.jsonl').read_text().splitlines()]


@pytest.mark.parametrize('entry', MANIFEST, ids=lambda e: e['name'])
def test_public_fixtures(tmp_path, entry):
    run, case = prepare(tmp_path, entry['name'])
    original = {p.name: p.read_bytes() for p in run.iterdir()}
    score = grade(run, case)
    assert score['quality_pass'] == (entry['exit_code'] == 0)
    assert set(entry['failed_assertion_ids']) <= set(score['failed_assertion_ids'])
    assert score['peer_review'] == 'pending'
    invoke('validate', 'scorecard', score)
    if score['quality_pass']:
        invoke('validate_run', case=read(case / 'case.json'), reference=read(case / 'reference.json'),
                               config=read(run / 'config.json'), claims=read(run / 'claims.json'),
                               report=read(run / 'report.json'), markdown=(run / 'report.md').read_text(),
                               events=events_read(run), scorecard=score)
    assert all((run / name).read_bytes() == contents for name, contents in original.items())


PUBLIC = [p.parent for p in sorted(CASES.glob('*/examples.json'))] + [p.parent for p in sorted(CASES.glob('*/variants/*/examples.json'))]


@pytest.mark.parametrize('case', PUBLIC, ids=lambda p: p.parent.name + '-' + p.name)
def test_public_correct_variants_and_negative_examples(tmp_path, case):
    run, _ = prepare(tmp_path, 'pass-' + read(case / 'case.json')['case_id'])
    examples = read(case / 'examples.json')
    for positive in examples['positive']:
        document = copy.deepcopy(positive['value'])
        # IDs are only hints, unordered sets and alternative wording are allowed.
        for c in document['claims']:
            c['reference_fact_ids'] = []
            if c['assertion']['type'] == 'string_set':
                c['assertion']['value'].reverse()
        config = read(run / 'config.json')
        config.update({k: document[k] for k in ('run_id', 'case_id', 'variant_id')})
        write(run / 'config.json', config)
        events = events_read(run)
        for e in events:
            e['run_id'] = document['run_id']
        trace_write(run, events)
        artifacts(run, document, positive['prose'])
        assert grade(run, case)['quality_pass'], positive['example_id']
    for negative in examples['negative']:
        document = copy.deepcopy(negative['value'])
        document['run_id'] = config['run_id']
        artifacts(run, document, negative.get('prose'))
        assert not grade(run, case)['quality_pass'], negative['example_id']


@pytest.mark.parametrize('fault', ['wrong-subspan', 'out-of-bounds', 'extra-citation', 'unknown-source', 'wrong-columns', 'missing-rows'])
def test_citation_rejects_valid_ids_with_inadequate_support(tmp_path, fault):
    run, case = prepare(tmp_path)
    document = read(run / 'claims.json')
    target = claim(document, 'C-percent' if fault in ('wrong-columns', 'missing-rows') else 'C-baseline')
    span = target['evidence'][0]
    if fault == 'wrong-subspan':
        span['end'] = span['start'] + 4
    elif fault == 'out-of-bounds':
        span['end'] = 100000
    elif fault == 'unknown-source':
        span['source_id'] = 'missing'
    elif fault == 'wrong-columns':
        span['columns'] = ['cost']
    elif fault == 'missing-rows':
        span['end'] -= 1
    else:
        target['evidence'].append(dict(source_id='EV-S14', kind='passage', start=0, end=10))
    artifacts(run, document)
    score = grade(run, case)
    assert score['required_fact_coverage'] == 1  # Correctness remains separate.
    assert 'citation.' + target['claim_id'] in score['failed_assertion_ids']
    assert not score['quality_pass']


def test_citation_split_rows_repeated_evidence_and_obsolete_correction(tmp_path):
    run, case = prepare(tmp_path)
    document = read(run / 'claims.json')
    for c in document['claims']:
        if c['evidence'] and c['evidence'][0]['kind'] == 'rows':
            span = c['evidence'].pop()
            c['evidence'] += [dict(span, start=1, end=3), dict(span, start=3, end=5), dict(span, start=1, end=3)]
    artifacts(run, document)
    assert grade(run, case)['quality_pass']
    run, case = prepare(tmp_path, 'pass-B')
    document = read(run / 'claims.json')
    c = claim(document, 'B-ledger-seconds')
    c['evidence'][0].update(source_id='EV-S05', start=413, end=763)  # Correct value, valid but obsolete passage.
    artifacts(run, document)
    score = grade(run, case)
    assert score['required_fact_coverage'] == 1
    assert 'citation.' + c['claim_id'] in score['failed_assertion_ids']
    # Repeated reports still identify one experiment, not three.
    c = claim(document, 'B-repair-q1-seconds')
    c['experiment_ids'].append('EV-E-Q2')
    artifacts(run, document)
    assert 'citation.' + c['claim_id'] in grade(run, case)['failed_assertion_ids']


@pytest.mark.parametrize('fault', ['intervention', 'unsupported-decision', 'unknown-factual', 'fake-uncertainty', 'premise'])
def test_gates_cannot_be_granted_by_candidate_flags(tmp_path, fault):
    run, case = prepare(tmp_path, 'pass-B')
    document = read(run / 'claims.json')
    if fault == 'intervention':
        events = events_read(run)
        events.insert(-1, dict(schema_version='1.0', event_id='human-help', run_id=events[0]['run_id'],
                               sequence=1, elapsed_ms=90, type='intervention', actor='human', action='steer'))
        events[-1]['intervention'] = True
        trace_write(run, events)
    elif fault == 'unsupported-decision':
        claim(document, 'B-recommendation')['assertion']['value'] = 'private-ledger'
    elif fault == 'unknown-factual':
        c = claim(document, 'B-slot-minutes')
        c.update(support_status='unknown', evidence=[])
    elif fault == 'premise':
        claim(document, 'B-ledger-seconds')['evidence'][0].update(start=0, end=10)
    else:
        document['claims'][-1]['assertion']['value'] = 'proven-superior'
    artifacts(run, document)
    score = grade(run, case)
    assert not score['quality_pass']
    field = {'intervention': 'intervention', 'unsupported-decision': 'no_unsupported_decision',
             'unknown-factual': 'all_factual_spans_valid', 'fake-uncertainty': 'uncertainty_pass',
             'premise': 'no_unsupported_decision'}[fault]
    assert score[field] == (fault == 'intervention')
    assert score['peer_review'] == 'pending'


def test_gates_accounting_and_budget_status_are_independent(tmp_path):
    run, case = prepare(tmp_path, 'pass-B')
    events = [json.loads(x) for x in (FIXED / 'schemas/examples/trace-B.jsonl').read_text().splitlines()]
    for e in events:
        e['run_id'] = read(run / 'config.json')['run_id']
        if e['type'] == 'tool_invocation':
            for key in ('input', 'result'):
                e[key]['run_id'] = e['run_id']
    trace_write(run, events)
    score = grade(run, case)
    assert score['quality_pass']
    assert (score['model_attempts'], score['logical_requests'], score['tool_invocations'], score['service_errors'], score['total_tokens']) == (2, 1, 2, 2, 360)
    events[0]['usage'] = dict.fromkeys(('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens'))
    events[0]['usage']['status'] = 'unknown'
    trace_write(run, events)
    score = grade(run, case)
    assert score['quality_pass'] and score['total_tokens'] is None
    assert read(run / 'grading.json')['budgets']['total_tokens']['status'] == 'unknown'
    events[0]['usage'] = dict(status='complete', input_tokens=30000, output_tokens=1,
                              cache_read_tokens=0, cache_write_tokens=0, reasoning_tokens=0)
    trace_write(run, events)
    assert grade(run, case)['quality_pass']  # Launcher admission is a different responsibility.
    assert read(run / 'grading.json')['budgets']['total_tokens']['status'] == 'exceeded'


def synthetic(tmp_path):
    run, case = prepare(tmp_path, 'pass-A')
    local_case = tmp_path / 'synthetic-case'
    shutil.copytree(case, local_case)
    reference = read(case / 'reference.json')
    reference['facts'] = reference['facts'][:5]
    reference['required_uncertainty'] = []
    for f in reference['facts']:
        f['decisive'] = False
    document = read(run / 'claims.json')
    document['claims'] = document['claims'][:5]
    return run, local_case, reference, document


@pytest.mark.parametrize(('count', 'decisive', 'expected'), [(4, False, True), (3, False, False), (4, True, False)])
def test_boundary_coverage_denominator_and_missing_decisive(tmp_path, count, decisive, expected):
    run, case, reference, document = synthetic(tmp_path)
    reference['facts'][-1]['decisive'] = decisive
    selected = document['claims'][:count]
    # Repeating the easiest claim cannot change the denominator/numerator.
    duplicate = copy.deepcopy(selected[0]); duplicate['claim_id'] = 'repeat'
    document['claims'] = selected + [duplicate]
    artifacts(run, document)
    write(case / 'reference.json', reference)
    score = grade(run, case)
    checks = score['grading_assertions']
    assert score['required_facts_total'] == 5 and score['required_facts_met'] == count
    assert score['quality_pass'] == expected
    if decisive:
        assert any(a['assertion_id'] == 'decisive.A-ledger-capacity' and not a['passed'] for a in checks)


@pytest.mark.parametrize(('value', 'absolute', 'relative', 'unit', 'expected'), [
    (20.01, .01, 0, 'percent', True), (19.99, .01, 0, 'percent', True),
    (20.0100001, .01, 0, 'percent', False), (19.9899999, .01, 0, 'percent', False),
    (22, 0, .1, 'percent', True), (22.000001, 0, .1, 'percent', False),
    (20, .01, 0, 'ratio', False), (20.02, .01, 0, 'percent', False)])
def test_boundary_numeric_reference_tolerance(value, absolute, relative, unit, expected):
    reference = dict(subject='test', predicate='metric', type='number', value=20, unit='percent',
                     tolerance=dict(absolute=absolute, relative=relative))
    actual = dict(reference, value=value, unit=unit, tolerance=dict(absolute=999, relative=999))
    assert grader_call('same_assertion', actual, reference) == expected


@pytest.mark.parametrize('fault', ['empty', 'missing-claims', 'missing-report', 'empty-prose', 'anchor', 'duplicate-ids', 'identity'])
def test_boundary_invalid_outputs_are_failed_quality(tmp_path, fault):
    run, case = prepare(tmp_path)
    document = read(run / 'claims.json')
    if fault == 'empty':
        document['claims'] = []
        write(run / 'claims.json', document)
    elif fault == 'missing-claims':
        (run / 'claims.json').unlink()
    elif fault == 'missing-report':
        (run / 'report.md').unlink()
    elif fault == 'empty-prose':
        (run / 'report.md').write_text('')
    elif fault == 'anchor':
        (run / 'report.md').write_text('<a id="claim-unrelated"></a>Text')
    else:
        if fault == 'duplicate-ids':
            document['claims'].append(copy.deepcopy(document['claims'][0]))
        else:
            document['run_id'] = 'different'
        write(run / 'claims.json', document)
    score = grade(run, case)
    assert not score['output_valid'] and not score['quality_pass']
    assert 'output.C' in score['failed_assertion_ids']


def test_peer_report_to_claim_to_real_evidence_links(tmp_path):
    run, case = prepare(tmp_path)
    document = read(run / 'claims.json')
    artifacts(run, document, 'On these paired days, the observed reduction is limited to deterministic demand.')
    score = grade(run, case)
    assert score['quality_pass'] and score['peer_review'] == 'pending'
    details = read(run / 'grading.json')
    target = next(c for c in details['claims'] if c['claim_id'] == 'claim-C-percent')
    assert target['supported_fact_ids'] == ['C-percent']
    resolved = target['evidence'][0]
    assert resolved['excerpt'][0]['cost'] == '100'
    assert Path(resolved['source_path']).is_file()
    text = (run / 'peer-review.md').read_text()
    for link in re.findall(r'\]\(([^)]+)\)', text):
        if link.startswith('file:'):
            assert Path(unquote(urlparse(link).path)).is_file()
        else:
            filename, _, anchor = link.partition('#')
            assert (run / filename).is_file()
            if anchor:
                assert f'<a id="{anchor}"></a>' in (run / filename).read_text()
    # Additional unstructured prose is deliberately a peer responsibility.
    with (run / 'report.md').open('a') as stream:
        stream.write('\nThis unrelated method is a world record holder.\n')
    assert grade(run, case)['peer_review'] == 'pending'


@pytest.mark.parametrize('fault', ['unfinished', 'corrupt', 'sequence', 'identity', 'policy'])
def test_offline_preflight_never_reads_reference_before_valid_end(tmp_path, fault):
    run, case = prepare(tmp_path)
    events = events_read(run)
    if fault == 'unfinished':
        events.pop()
    elif fault == 'sequence':
        events[0]['sequence'] = 99
    elif fault == 'identity':
        events[0]['run_id'] = 'wrong'
    if fault == 'corrupt':
        (run / 'trace.jsonl').write_text('{corrupt')
    else:
        (run / 'trace.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))
    if fault == 'policy':
        config = read(run / 'config.json'); config['policy_sha256'] = '0' * 64
        write(run / 'config.json', config)
    program = """import json, sys
from pathlib import Path
from exercises.fixed.grading import engine
reads = []
original = engine.read
def observe(path):
    reads.append(path.name)
    return original(path)
engine.read = observe
try:
    engine.grade_run(*map(Path, sys.argv[1:]))
except ValueError:
    print(json.dumps(reads))
else:
    raise AssertionError('invalid run accepted')
"""
    result = subprocess.run([sys.executable, '-c', program, str(run), str(case), str(POLICY)],
                            cwd=SESSION, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'reference.json' not in json.loads(result.stdout)
    assert not (run / 'scorecard.json').exists()


def test_offline_no_network_or_credentials(tmp_path):
    run, case = prepare(tmp_path)
    program = """import os, socket, sys
from pathlib import Path
from exercises.fixed.grading import engine
def forbidden(*args, **kwargs):
    raise AssertionError('grading attempted network access')
socket.socket = forbidden
socket.create_connection = forbidden
for key in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
    os.environ.pop(key, None)
assert engine.grade_run(*map(Path, sys.argv[1:]))['quality_pass']
"""
    result = subprocess.run([sys.executable, '-c', program, str(run), str(case), str(POLICY)],
                            cwd=SESSION, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(('name', 'expected'), [('pass-A', 0), ('right-source-wrong-span', 1), ('malformed-claims', 1)])
def test_offline_cli_exit_and_artifacts(tmp_path, name, expected):
    run, case = prepare(tmp_path, name)
    result = subprocess.run([sys.executable, str(FIXED / 'grade.py'), '--run', str(run), '--case', str(case),
                             '--policy', str(POLICY)], capture_output=True, text=True, cwd=tmp_path, check=False)
    assert result.returncode == expected, result.stdout + result.stderr
    assert json.loads(result.stdout)['peer_review'] == 'pending'
    assert (run / 'scorecard.json').exists() and (run / 'peer-review.md').exists()
