"""Examiner probe: real dispatcher finds every decisive passage among distractors, for every case and variant."""

import json
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

SESSION = Path(__file__).resolve().parents[2]
CASES = sorted((SESSION / 'exercises/cases').rglob('reference.json'))


def dispatch(root, tool, arguments):
    request = dict(tool=tool, arguments=arguments, run_id='probe', tool_call_id='probe-1')
    done = subprocess.run([sys.executable, '-m', 'exercises.fixed.bridge.dispatch', str(root)], cwd=SESSION,
                          input=json.dumps(request), capture_output=True, text=True, encoding='utf-8', check=True)
    return json.loads(done.stdout)


def decisive_passages(reference):
    for fact in reference['facts']:
        if fact.get('decisive'):
            for span in fact['accepted_evidence']:
                if span['kind'] == 'passage':
                    yield fact['fact_id'], span


@pytest.mark.parametrize('reference', CASES, ids=lambda p: str(p.parent.relative_to(SESSION / 'exercises/cases')))
def test_decisive_passages_found_among_distractors(reference):
    root = reference.parent
    ref = json.loads(reference.read_text(encoding='utf-8'))
    corpus = json.loads((root / 'corpus.json').read_text(encoding='utf-8'))
    total = sum(len(s.get('passages', [])) for s in corpus['sources'])
    spans = list(decisive_passages(ref))
    assert spans, 'case has no decisive passage evidence'
    for fact_id, span in spans:
        text = dispatch(root, 'read', dict(source_id=span['source_id'], start=span['start'], end=span['end']))
        assert text['result']['status'] == 'ok', fact_id
        words = list(dict.fromkeys(w for w in re.findall(r'\w+', text['result']['data']['text'].casefold()) if len(w) > 4))[:10]
        query = ' '.join(words)
        first = dispatch(root, 'search', dict(query=query))
        assert first == dispatch(root, 'search', dict(query=query))
        hits = first['audit']['hits']
        assert first['audit']['total_hits'] <= total
        assert any(h['passage_span']['source_id'] == span['source_id']
                   and h['passage_span']['start'] < span['end'] and span['start'] < h['passage_span']['end']
                   for h in hits), (fact_id, query, hits)


@pytest.mark.parametrize('reference', [p for p in CASES if 'c-audit' in p.parts],
                         ids=lambda p: str(p.parent.relative_to(SESSION / 'exercises/cases')))
def test_check_table_matches_public_reference_rows_and_totals(reference):
    root = reference.parent
    ref = {f['fact_id']: f['assertion'] for f in json.loads(reference.read_text(encoding='utf-8'))['facts']}
    corpus = json.loads((root / 'corpus.json').read_text(encoding='utf-8'))
    table = next(s for s in corpus['sources'] if s['path'].endswith('.csv'))
    lines = (root / table['path']).read_text(encoding='utf-8').splitlines()
    header = lines[0].split(',')
    rows = [dict(zip(header, line.split(','))) for line in lines[1:]]
    methods = list(dict.fromkeys(r['method'] for r in rows))
    baseline = ref['C-baseline']['value']
    candidate = next(m for m in methods if m != baseline)
    args = dict(source_id=table['source_id'], method_left=baseline, method_right=candidate, metric='cost',
                unit=table['units']['cost'], feasible_only=True, pair_key='pair_id',
                pair_ids=sorted({r['pair_id'] for r in rows}))
    reply = dispatch(root, 'check_table', args)
    assert reply['result']['status'] == 'ok'
    included = {p[k] for p in reply['audit']['pairs'] for k in ('left_row_id', 'right_row_id')}
    assert included == set(ref['C-rows']['value'])
    assert len(reply['result']['data']['pairs']) == ref['C-pairs']['value']
    for fact_id, assertion in ref.items():
        if assertion['type'] == 'number' and assertion['predicate'] in ('baseline_total', 'candidate_total'):
            assert Decimal(str(reply['audit'][assertion['predicate']])) == Decimal(str(assertion['value'])), fact_id
    # Rejected: a code-like operation never runs.
    bad = dispatch(root, 'check_table', {**args, 'operation': "__import__('os').system('touch PWNED')"})
    assert bad['result']['error'] == dict(code='invalid_input', retryable=False)
    assert not (SESSION / 'PWNED').exists()
