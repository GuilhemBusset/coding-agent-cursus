"""Offline dossier integrity and public fact examples, not a runtime evaluator.

Entailment, acceptable paraphrases and teaching quality also receive content review.
No API, external corpus, solver or Session 1 input is used here.
"""

import copy
import json
import shutil
import unicodedata
from datetime import date
from pathlib import Path

import pytest
from test_contracts import invoke

CASES = Path(__file__).resolve().parents[2] / 'exercises' / 'cases'
NAMES = ['a-find', 'b-compare']


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def bundle(path):
    return {name: read(path / f'{name}.json') for name in ['case', 'corpus', 'reference']}


def indexed(items, key):
    result = {item[key]: item for item in items}
    assert len(result) == len(items), f'duplicate {key}'
    return result


def resolve(span, sources):
    assert span['kind'] == 'passage'
    assert span['source_id'] in sources, 'unknown source'
    source = sources[span['source_id']]
    assert 0 <= span['start'] < span['end'] <= source['length'], 'invalid span bounds'
    assert any((p['start'], p['end']) == (span['start'], span['end'])
               for p in source['passages']), 'span does not resolve to an accepted passage'


def check_assets(path, case, corpus, reference):
    invoke('validate', 'case', case)
    invoke('validate', 'reference', reference)
    assert (case['case_id'], case['variant_id']) == (reference['case_id'], reference['variant_id'])
    assert case['corpus_id'] == corpus['corpus_id']
    assert case['reference_path'] == f'cases/{path.name}/reference.json'
    sources = indexed(copy.deepcopy(corpus['sources']), 'source_id')
    experiments = indexed(corpus['experiments'], 'experiment_id')
    facts = indexed(reference['facts'], 'fact_id')
    history = indexed(corpus['historical_facts'], 'fact_id')
    passage_ids = []
    for sid, source in sources.items():
        local_path = Path(source['path'])
        assert not local_path.is_absolute() and '..' not in local_path.parts, 'nonlocal source'
        text = unicodedata.normalize('NFC', (path / local_path).read_text(encoding='utf-8'))
        source['length'] = len(text)
        date.fromisoformat(source['date'])
        assert source['fictional'] is True and source['provenance']
        assert source['reporting_relationship']
        for passage in source['passages']:
            passage_ids.append(passage['passage_id'])
            assert passage['passage_id'].startswith(sid + ':'), 'passage source identity'
            assert 0 <= passage['start'] < passage['end'] <= len(text), 'invalid span bounds'
            assert text[passage['start']:passage['end']] == passage['quote'], 'passage quote mismatch'
        assert set(source['experiment_ids']) <= experiments.keys(), 'unknown experiment'
        families = {experiments[e]['family_id'] for e in source['experiment_ids']}
        assert set(source['experiment_family_ids']) == families, 'experiment family mismatch'
        for old in source['supersedes_source_ids']:
            assert old in sources and sources[old]['date'] < source['date'], 'correction date/source'
    assert len(passage_ids) == len(set(passage_ids)), 'duplicate passage ID'
    mapped = {e['experiment_id']: set(e['source_ids']) for e in reference['experiments']}
    expected = {eid: {sid for sid, s in sources.items() if eid in s['experiment_ids']}
                for eid in experiments}
    assert mapped == expected, 'experiment source mapping mismatch'
    used_corrections = set()
    for fact in facts.values():
        for span in fact['accepted_evidence']:
            resolve(span, sources)
        for eid in fact['experiment_ids']:
            # A summary can mention an experiment without being another primary
            # report of it (EV-S10:P02 names both independent Queue Repair runs).
            assert any(span['source_id'] in mapped[eid] or any(
                eid in p['quote'] for p in sources[span['source_id']]['passages']
                if (p['start'], p['end']) == (span['start'], span['end']))
                for span in fact['accepted_evidence']), 'fact experiment mismatch'
        for old in fact['supersedes_fact_ids']:
            assert old in history, 'unknown historical fact'
            prior = history[old]
            assert prior['replacement_fact_id'] == fact['fact_id'], 'replacement fact mismatch'
            corrected = sources[prior['superseded_by_source_id']]
            used_corrections.add((corrected['source_id'], prior['source_id'], fact['fact_id']))
            assert prior['source_id'] in corrected['supersedes_source_ids'], 'historical correction mismatch'
            assert any(p['passage_id'] == prior['passage_id'] for p in sources[prior['source_id']]['passages']), 'historical passage mismatch'
            assert any(s['source_id'] == corrected['source_id'] for s in fact['accepted_evidence']), 'replacement evidence mismatch'
    for correction in reference['corrections']:
        assert correction['source_id'] in sources, 'unknown correction source'
        source = sources[correction['source_id']]
        assert correction['supersedes_source_id'] in source['supersedes_source_ids'], 'correction source mismatch'
        for fid in correction['affected_fact_ids']:
            assert any(s['source_id'] == source['source_id'] for s in facts[fid]['accepted_evidence']), 'correction affected fact mismatch'
    declared_corrections = {(c['source_id'], c['supersedes_source_id'], fid)
                            for c in reference['corrections'] for fid in c['affected_fact_ids']}
    assert used_corrections <= declared_corrections, 'missing correction record'
    return sources


@pytest.mark.parametrize('name', NAMES)
def test_standalone_case_contracts_and_all_accepted_spans(name, tmp_path):
    # Only this folder is copied: a hidden dependency on A, B or P01 cannot resolve.
    isolated = tmp_path / name
    shutil.copytree(CASES / name, isolated)
    check_assets(isolated, **bundle(isolated))


@pytest.mark.parametrize('mutation', ['unknown-source', 'empty', 'outside', 'unregistered-span',
                                    'wrong-quote', 'duplicate-passage', 'passage-source'])
def test_rejects_broken_ids_and_spans(mutation):
    data = bundle(CASES / 'a-find')
    span = data['reference']['facts'][0]['accepted_evidence'][0]
    passage = data['corpus']['sources'][0]['passages'][0]
    if mutation == 'unknown-source':
        span['source_id'] = 'missing'
        error = 'unknown source'
    elif mutation == 'empty':
        span['end'] = span['start']
        error = 'nonempty'
    elif mutation == 'outside':
        span['end'] = 10**7
        error = 'invalid span bounds'
    elif mutation == 'unregistered-span':
        span['start'] += 1
        error = 'does not resolve'
    elif mutation == 'wrong-quote':
        passage['quote'] += ' altered'
        error = 'quote mismatch'
    elif mutation == 'duplicate-passage':
        data['corpus']['sources'][0]['passages'].append(copy.deepcopy(passage))
        error = 'duplicate passage'
    else:
        passage['passage_id'] = 'missing:P01'
        error = 'passage source identity'
    with pytest.raises((AssertionError, ValueError), match=error):
        check_assets(CASES / 'a-find', **data)


@pytest.mark.parametrize('mutation', ['correction-source', 'superseded-source', 'affected-fact',
                                    'experiment-reports', 'family', 'fact-experiment', 'historical-fact',
                                    'omitted-correction'])
def test_rejects_mismatched_corrections_and_experiments(mutation):
    data = bundle(CASES / 'b-compare')
    ref = data['reference']
    correction = ref['corrections'][0]
    facts = indexed(ref['facts'], 'fact_id')
    if mutation == 'correction-source':
        correction['source_id'] = 'EV-S07'
        error = 'correction source mismatch'
    elif mutation == 'superseded-source':
        correction['supersedes_source_id'] = 'EV-S04'
        error = 'correction source mismatch'
    elif mutation == 'affected-fact':
        correction['affected_fact_ids'] = ['B-private-exclusion']
        error = 'correction affected fact mismatch'
    elif mutation == 'experiment-reports':
        next(e for e in ref['experiments'] if e['experiment_id'] == 'EV-E-Q1')['source_ids'] = ['EV-S10']
        error = 'experiment source mapping mismatch'
    elif mutation == 'family':
        next(s for s in data['corpus']['sources'] if s['source_id'] == 'EV-S08')['experiment_family_ids'] = ['EV-F-D']
        error = 'experiment family mismatch'
    elif mutation == 'fact-experiment':
        facts['B-repair-q1-seconds']['experiment_ids'] = ['EV-E-Q2']
        error = 'fact experiment mismatch'
    elif mutation == 'historical-fact':
        facts['B-ledger-ineligible']['supersedes_fact_ids'] = ['missing']
        error = 'unknown historical fact'
    else:
        ref['corrections'] = []
        error = 'missing correction record'
    with pytest.raises(AssertionError, match=error):
        check_assets(CASES / 'b-compare', **data)


def assertion_key(assertion):
    value = copy.deepcopy(assertion)
    if value['type'] == 'string_set':
        value['value'].sort()
    return value


@pytest.mark.parametrize('name', NAMES)
def test_public_fact_examples(name):
    path = CASES / name
    data = bundle(path)
    sources = check_assets(path, **data)
    facts = data['reference']['facts']
    examples = read(path / 'examples.json')
    for group in ['positive', 'negative']:
        for example in examples[group]:
            claims = example['value']
            invoke('validate', 'claims', claims)
            assert (claims['case_id'], claims['variant_id']) == (data['case']['case_id'], data['case']['variant_id'])
            by_assertion = {(c['assertion']['subject'], c['assertion']['predicate']): c for c in claims['claims']}
            differences = set()
            for fact in facts:
                a = fact['assertion']
                claim = by_assertion.get((a['subject'], a['predicate']))
                if claim is None or assertion_key(claim['assertion']) != assertion_key(a):
                    differences.add(fact['fact_id'])
                elif group == 'positive':
                    assert claim['support_status'] == 'supported'
                    assert claim['reference_fact_ids'] == [fact['fact_id']]
                    assert claim['experiment_ids'] == fact['experiment_ids']
                    assert claim['evidence'] and all(s in fact['accepted_evidence'] for s in claim['evidence'])
            assert differences == set(example.get('failed_fact_ids', []))
            for claim in claims['claims']:
                for span in claim['evidence']:
                    resolve(span, sources)
            if group == 'positive':
                for requirement in data['reference']['required_uncertainty']:
                    uncertain = by_assertion[(requirement['subject'], requirement['predicate'])]
                    assert uncertain['kind'] == 'uncertainty' and uncertain['support_status'] == 'unknown'


def test_wrong_examples_have_identifiable_evidence_failures():
    path = CASES / 'b-compare'
    data = bundle(path)
    examples = {e['example_id']: e for e in read(path / 'examples.json')['negative']}
    ref = indexed(data['reference']['facts'], 'fact_id')
    stale = next(c for c in examples['obsolete-eligibility']['value']['claims']
                 if c['reference_fact_ids'] == ['B-ledger-ineligible'])
    assert all(s not in ref['B-ledger-ineligible']['accepted_evidence'] for s in stale['evidence'])
    old_source = stale['evidence'][0]['source_id']
    assert any(c['supersedes_source_id'] == old_source for c in data['reference']['corrections'])
    duplicate = next(c for c in examples['double-counted-experiments']['value']['claims']
                     if c['reference_fact_ids'] == ['B-independent-count'])
    sources = indexed(data['corpus']['sources'], 'source_id')
    experiments = {eid for s in duplicate['evidence'] for eid in sources[s['source_id']]['experiment_ids']}
    assert set(duplicate['experiment_ids']) == experiments
    assert duplicate['assertion']['value'] == len(duplicate['evidence']) > len(experiments)
    assert ref['B-independent-count']['assertion']['value'] == len(experiments)
