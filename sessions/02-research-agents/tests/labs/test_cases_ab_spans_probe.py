"""Examiner probe for #181 A1: independent span resolution and extra rejections.

Resolves every accepted reference span itself (universal newlines, NFC, code
points) in an isolated copy of each case, and checks further broken-ID and
mismatched correction/experiment mutations through the shipped asset check.
"""

import shutil
import unicodedata
from pathlib import Path

import pytest
from test_cases_ab import bundle, check_assets
from test_contracts import ContractError, invoke

CASES = Path(__file__).resolve().parents[2] / 'exercises' / 'cases'


@pytest.mark.parametrize('name', ['a-find', 'b-compare'])
def test_every_accepted_span_is_exact_bundled_text(name, tmp_path):
    isolated = tmp_path / name
    shutil.copytree(CASES / name, isolated)
    data = bundle(isolated)
    invoke('validate', 'reference', data['reference'])
    invoke('validate', 'case', data['case'])
    sources = {s['source_id']: s for s in data['corpus']['sources']}
    spans = 0
    for fact in data['reference']['facts']:
        assert fact['accepted_evidence'], fact['fact_id']
        for span in fact['accepted_evidence']:
            source = sources[span['source_id']]
            path = (isolated / source['path']).resolve()
            assert path.is_relative_to(isolated.resolve())
            with path.open(encoding='utf-8') as handle:  # universal newlines
                text = unicodedata.normalize('NFC', handle.read())
            excerpt = text[span['start']:span['end']]
            assert excerpt.strip(), (fact['fact_id'], span)
            quotes = {p['quote'] for p in source['passages']}
            assert excerpt in quotes, (fact['fact_id'], span)
            spans += 1
    assert spans >= len(data['reference']['facts'])


def mutate(data, mutation):
    ref, corpus = data['reference'], data['corpus']
    facts = {f['fact_id']: f for f in ref['facts']}
    source = {s['source_id']: s for s in corpus['sources']}
    if mutation == 'fact-unknown-experiment':
        facts['B-repair-q2-seconds']['experiment_ids'] = ['EV-E-ZZ']
    elif mutation == 'corpus-unknown-experiment':
        source['EV-S10']['experiment_ids'] = ['EV-E-ZZ']
    elif mutation == 'correction-predates-original':
        source['EV-S06']['date'] = '2026-10-01'
    elif mutation == 'experiment-unknown-report':
        ref['experiments'][0]['source_ids'] = ['EV-S99']
    elif mutation == 'empty-b-span':
        span = facts['B-ledger-seconds']['accepted_evidence'][0]
        span['end'] = span['start']
    else:
        facts['B-ledger-seconds']['accepted_evidence'][0]['source_id'] = 'EV-S99'


@pytest.mark.parametrize('mutation', ['fact-unknown-experiment', 'corpus-unknown-experiment',
                                      'correction-predates-original', 'experiment-unknown-report',
                                      'empty-b-span', 'unknown-b-source'])
def test_b_rejects_further_broken_references(mutation):
    data = bundle(CASES / 'b-compare')
    mutate(data, mutation)
    with pytest.raises((AssertionError, ContractError)):
        check_assets(CASES / 'b-compare', **data)
