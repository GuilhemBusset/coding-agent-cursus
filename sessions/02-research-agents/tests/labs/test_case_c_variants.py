"""Independent offline arithmetic, public bundle integrity and seeded generation.

These are asset checks, not a runtime grader or a claim about live model outputs.
"""

import copy
import csv
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from test_cases_ab import bundle, check_assets, indexed, read
from test_contracts import invoke

SESSION = Path(__file__).resolve().parents[2]
EXERCISES = SESSION / 'exercises'
PUBLIC = EXERCISES / 'fixed/config/public'
MANIFEST = read(PUBLIC / 'manifest.json')
C = EXERCISES / 'cases/c-audit'


def asset_call(function, *args):
    # Import from the standalone session working directory, like test_contracts.invoke.
    program = """import json, sys
from pathlib import Path
from exercises.fixed.corpus import audit
request = json.load(sys.stdin)
args = request['args']
if request['function'] == 'load_rows':
    args[0] = Path(args[0])
try:
    print(json.dumps({'value': getattr(audit, request['function'])(*args)}))
except ValueError as error:
    print(json.dumps({'error': str(error)}))
"""
    process = subprocess.run([sys.executable,'-c',program],cwd=SESSION,
                             input=json.dumps(dict(function=function,args=args),default=str),
                             capture_output=True,text=True)
    assert process.returncode == 0, process.stdout + process.stderr
    response = json.loads(process.stdout)
    if 'error' in response:
        raise ValueError(response['error'])
    return response['value']


def independent_result(path, baseline, candidate):
    # Read CSV directly, without the generator calculation or reference as oracle.
    with path.open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    groups = {}
    for row in rows:
        groups.setdefault((row['instance_id'], row['run_id']), []).append(row)
    selected = []
    for group in groups.values():
        left = [r for r in group if r['method'] == baseline]
        right = [r for r in group if r['method'] == candidate]
        if len(group) == 2 and len(left) == len(right) == 1 and all(r['feasible'] == 'true' for r in group):
            selected.extend([left[0], right[0]])
    totals = [sum(Decimal(r['cost']) for r in selected if r['method'] == method) for method in (baseline, candidate)]
    ratio = (totals[0] - totals[1]) / totals[0]
    return rows, selected, dict(baseline_total=totals[0], candidate_total=totals[1], pair_count=Decimal(len(selected) // 2), reduction_ratio=ratio, reduction_percent=100 * ratio)


def c_reference(path, data):
    case, corpus, reference = (data[k] for k in ('case', 'corpus', 'reference'))
    invoke('validate', 'case', case)
    invoke('validate', 'reference', reference)
    assert case['case_id'] == reference['case_id'] == 'C'
    assert case['variant_id'] == reference['variant_id']
    assert case['corpus_id'] == corpus['corpus_id']
    facts = indexed(reference['facts'], 'fact_id')
    sources = indexed(corpus['sources'], 'source_id')
    table = next(s for s in sources.values() if s['path'].endswith('.csv'))
    baseline = facts['C-baseline']['assertion']['value']
    candidate, = {r['method'] for r in asset_call('load_rows', path / table['path'])} - {baseline}
    rows, selected, result = independent_result(path / table['path'], baseline, candidate)
    for fact in facts.values():
        assert fact['required'] and fact['decisive']
        a = fact['assertion']
        if a['predicate'] in result:
            assert Decimal(str(a['value'])) == result[a['predicate']], 'numeric reference mismatch'
        if a['type'] == 'number':
            tolerance = 0.01 if a['predicate'] == 'reduction_percent' else 0.0001 if a['predicate'] == 'reduction_ratio' else 0
            assert a['tolerance'] == {'absolute': tolerance, 'relative': 0}
        covered = set()
        for span in fact['accepted_evidence']:
            source = sources[span['source_id']]
            if span['kind'] == 'rows':
                assert source is table and 1 <= span['start'] < span['end'] <= len(rows) + 1
                assert set(table['columns']) <= set(span['columns']), 'incomplete row columns'
                covered.update(r['row_id'] for r in rows[span['start'] - 1:span['end'] - 1])
            else:
                assert any((p['start'], p['end']) == (span['start'], span['end']) for p in source['passages']), 'unregistered span'
        if any(s['kind'] == 'rows' for s in fact['accepted_evidence']):
            assert {r['row_id'] for r in selected} <= covered, 'incomplete paired row evidence'
    for source in sources.values():
        text = unicodedata.normalize('NFC', (path / source['path']).read_text(encoding='utf-8'))
        for passage in source['passages']:
            assert passage['passage_id'].startswith(source['source_id'] + ':')
            assert text[passage['start']:passage['end']] == passage['quote'], 'quote mismatch'
    assert facts['C-rows']['assertion']['value'] == [r['row_id'] for r in selected]
    assert facts['C-scope']['assertion']['value'] is False, 'unsupported superiority'
    assert reference['required_uncertainty'] == [dict(requirement_id='C-uncertain-demand',subject=candidate,predicate='performance_under_uncertain_demand',reason='missing_evidence')], 'missing uncertainty'
    experiments = indexed(corpus['experiments'], 'experiment_id')
    assert {r['experiment_id'] for r in rows} == set(experiments)
    assert set(table['row_ids']) == {r['row_id'] for r in rows}
    assert set(table['experiment_family_ids']) == {e['family_id'] for e in experiments.values()}
    assert reference['experiments'] == [dict(experiment_id=e, source_ids=[table['source_id']]) for e in experiments]
    return result


def test_audit_base_independent_worksheet():
    rows, selected, result = independent_result(C / 'sources/EV-T01.csv', 'audit-a', 'audit-b')
    assert [r['row_id'] for r in selected] == [f'EV-T01:R{i:04d}' for i in range(1, 5)]
    assert {r['pair_id'] for r in selected} == {'EV-PAIR-0001', 'EV-PAIR-0002'}
    assert {r['row_id'] for r in rows} - {r['row_id'] for r in selected} == {f'EV-T01:R{i:04d}' for i in range(5, 9)}
    assert result == dict(baseline_total=Decimal(300),candidate_total=Decimal(240),pair_count=Decimal(2),reduction_ratio=Decimal('.2'),reduction_percent=Decimal(20))
    pair_mean = ((Decimal(100) - 90) / 100 + (Decimal(200) - 150) / 200) * 50
    assert pair_mean == Decimal('17.5') != result['reduction_percent']
    print('Independent worksheet: included R0001–R0004; excluded R0005–R0008; A=100+200=300, B=90+150=240; 100*(300-240)/300=20 percent; ratio=0.2; means=150/120; pairwise mean=17.5 (wrong aggregation).')
    c_reference(C, bundle(C))
    actual = asset_call('paired_result', asset_call('load_rows', C / 'sources/EV-T01.csv'), 'audit-a', 'audit-b')
    assert actual['row_ids'] == [r['row_id'] for r in selected]
    for key, expected in result.items():
        assert Decimal(str(actual[key])) == expected


@pytest.mark.parametrize('value,accepted', [('20',True),('19.99',True),('20.01',True),('19.989999',False),('20.010001',False),('0.2',False),('NaN',False)])
def test_numeric_tolerance(value, accepted):
    assert asset_call('within_tolerance', value, '20', '0.01') is accepted
    assert asset_call('within_tolerance', '0.2001', '0.2', '0.0001')
    assert not asset_call('within_tolerance', '0.2001001', '0.2', '0.0001')


@pytest.mark.parametrize('mutation,error', [('malformed','malformed row'),('duplicate','duplicate row'),('duplicate-method','ambiguous'),('pair-collision','pair identity'),('split-pair','multiple pair'),('cost','integer cost')])
def test_invalid_row_data(mutation, error, tmp_path):
    rows = asset_call('load_rows', C / 'sources/EV-T01.csv')
    if mutation == 'malformed': rows[0]['row_id'] = 'R1'
    elif mutation == 'duplicate': rows[1]['row_id'] = rows[0]['row_id']
    elif mutation == 'duplicate-method': rows[1]['method'] = rows[0]['method']
    elif mutation == 'pair-collision': rows[2]['pair_id'] = rows[3]['pair_id'] = rows[0]['pair_id']
    elif mutation == 'split-pair': rows[1]['pair_id'] = 'EV-PAIR-0099'
    else: rows[0]['cost'] = 'NaN'
    path = tmp_path / 'invalid.csv'
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError,match=error): asset_call('load_rows', path)


def test_announced_variants_regenerate():
    with TemporaryDirectory(prefix='public variants ') as first, TemporaryDirectory(prefix='public variants ') as second:
        for directory in (first, second):
            process = subprocess.run([sys.executable,'-m','exercises.fixed.corpus.variants','--out',directory],cwd=SESSION,capture_output=True,text=True)
            assert process.returncode == 0, process.stdout + process.stderr
            print(process.stdout)
        for entry in MANIFEST['variants']:
            for generated_root in (Path(first), Path(second)):
                generated, published = generated_root / entry['path'], EXERCISES / entry['path']
                actual = {p.relative_to(generated):p.read_bytes() for p in generated.rglob('*') if p.is_file()}
                expected = {p.relative_to(published):p.read_bytes() for p in published.rglob('*') if p.is_file()}
                assert actual == expected


def b_relationships(path, data, provenance):
    mapping = provenance['mappings']
    sources = indexed(data['corpus']['sources'], 'source_id')
    facts = indexed(data['reference']['facts'], 'fact_id')
    def seconds(sid):
        text = (path / sources[mapping['sources'][sid]]['path']).read_text(encoding='utf-8')
        match = re.search(r'\b(\d+) seconds', text)
        assert match, 'missing timing in primary source'
        return int(match[1])
    for fid, sid in [('B-ledger-seconds','EV-S06'),('B-repair-q1-seconds','EV-S07'),('B-repair-q2-seconds','EV-S10'),('B-private-seconds','EV-S11')]:
        assert facts[fid]['assertion']['value'] == seconds(sid), 'numeric reference mismatch'
    assert seconds('EV-S06') > 60 >= max(seconds('EV-S07'), seconds('EV-S10'), seconds('EV-S11')), 'timing constraints'
    assert facts['B-both-constraints']['assertion']['value'] == ['finite-shared-chargers','solve-at-most-60-seconds']
    assert facts['B-recommendation']['assertion']['value'] == mapping['methods']['queue-repair']
    assert facts['B-ledger-capacity']['assertion']['value'] is True
    assert facts['B-private-exclusion']['assertion']['value'] is False
    assert facts['B-ledger-ineligible']['assertion']['value'] is False
    assert sources[mapping['sources']['EV-S06']]['supersedes_source_ids'] == [mapping['sources']['EV-S05']]
    repeats = {e for sid in ['EV-S07','EV-S08','EV-S09'] for e in sources[mapping['sources'][sid]]['experiment_ids']}
    assert len(repeats) == 1
    assert not repeats & set(sources[mapping['sources']['EV-S10']]['experiment_ids'])
    assert facts['B-independent-count']['assertion']['value'] == 2


@pytest.mark.parametrize('entry',MANIFEST['variants'],ids=lambda e:e['case_id'])
def test_variant_references_and_decisive_requirements(entry):
    path = EXERCISES / entry['path']
    data, provenance = bundle(path), read(path / 'provenance.json')
    base = bundle(EXERCISES / provenance['base_path'])
    mapping = provenance['mappings']
    assert provenance['seed'] == entry['seed']
    assert data['case']['variant_id'] == entry['variant_id']
    assert provenance['source_order'] == [s['source_id'] for s in data['corpus']['sources']]
    assert provenance['source_order'] != [mapping['sources'][s['source_id']] for s in base['corpus']['sources']]
    for group, key in [('sources','source_id'),('experiments','experiment_id')]:
        assert set(mapping[group]) == {s[key] for s in base['corpus'][group]}
        assert set(mapping[group].values()) == {s[key] for s in data['corpus'][group]}
    assert set(mapping['passages'].values()) == {p['passage_id'] for s in data['corpus']['sources'] for p in s['passages']}
    if entry['case_id'] == 'C':
        result = c_reference(path,data)
        assert result['reduction_percent'] != 20
        print('Independent seeded C worksheet:', result)
    else:
        with TemporaryDirectory() as temporary:
            isolated = Path(temporary) / provenance['base_path'].split('/')[-1]
            shutil.copytree(path, isolated)
            check_assets(isolated, **data)
        if entry['case_id'] == 'B': b_relationships(path,data,provenance)
        else:
            facts = indexed(data['reference']['facts'],'fact_id')
            assert set(facts['A-method-set']['assertion']['value']) == {mapping['methods'][m] for m in ['slot-ledger','queue-repair']}
    for examples in read(path / 'examples.json').values():
        for example in examples:
            invoke('validate','claims',example['value'])
            for claim in example['value']['claims']:
                for span in claim['evidence']:
                    assert span['source_id'] in mapping['sources'].values()
                    if span['kind'] == 'passage':
                        source = next(s for s in data['corpus']['sources'] if s['source_id'] == span['source_id'])
                        assert any((p['start'],p['end']) == (span['start'],span['end']) for p in source['passages'])


@pytest.mark.parametrize('mutation', ['quote','row-span','columns','superiority','uncertainty','timing','correction'])
def test_broken_variant_relationships_rejected(mutation):
    entry = MANIFEST['variants'][1 if mutation in ('timing','correction') else 2]
    path = EXERCISES / entry['path']
    data = copy.deepcopy(bundle(path))
    if mutation == 'quote': data['corpus']['sources'][0]['passages'][0]['quote'] += ' broken'
    elif mutation == 'row-span': data['reference']['facts'][0]['accepted_evidence'][0]['end'] = 3
    elif mutation == 'columns': data['reference']['facts'][0]['accepted_evidence'][0]['columns'] = ['cost']
    elif mutation == 'superiority': data['reference']['facts'][-1]['assertion']['value'] = True
    elif mutation == 'uncertainty': data['reference']['required_uncertainty'] = []
    elif mutation == 'timing': data['reference']['facts'][3]['assertion']['value'] = 40
    else: data['reference']['facts'][4]['assertion']['value'] = True
    with pytest.raises(AssertionError):
        if entry['case_id'] == 'C': c_reference(path,data)
        else: b_relationships(path,data,read(path / 'provenance.json'))


def test_public_manifest_schedule_and_fault_resolution():
    policy = read(EXERCISES / 'fixed/config/policy.v1.json')
    invoke('validate','policy',policy)
    assert MANIFEST['schedule'] == policy['schedule']
    for mode, count in [('class',1),('submission',3)]:
        for entry in MANIFEST['variants']:
            trials = [t for t in MANIFEST['schedule'][mode] if t['case_id'] == entry['case_id']]
            assert entry[f'{mode}_trials'] == count
            assert trials == [dict(case_id=entry['case_id'],variant_id=entry['variant_id'],trial=i,seed=entry['seed']) for i in range(1,count+1)]
            assert (EXERCISES / entry['path'] / 'reference.json').is_file()
    scenarios = MANIFEST['fault_scenarios']
    assert {e['scenario_id'] for e in scenarios} == {p.stem for p in (PUBLIC / 'faults').glob('*.json')}
    assert len(scenarios) == len({e['scenario_id'] for e in scenarios}) == 11
    for entry in scenarios:
        fixture = read(EXERCISES / entry['path'])
        assert fixture['scenario_id'] == entry['scenario_id']
        assert all(fixture[k] for k in ['operation','preconditions','trigger','responses','solution','expected_accounting','expected_stop_reason'])


def test_audit_public_examples_require_rows_and_uncertainty():
    def complete(example, reference):
        claims = example['value']['claims']
        for fact in reference['facts']:
            claim, = [c for c in claims if c['reference_fact_ids'] == [fact['fact_id']]]
            assert claim['assertion'] == fact['assertion'], 'changed factual conclusion'
            assert claim['support_status'] == 'supported' and claim['evidence'], 'missing evidence'
            # Published positives use the canonical complete evidence; alternatives are reviewed.
            assert claim['evidence'] == fact['accepted_evidence'], 'incomplete row evidence'
        for requirement in reference['required_uncertainty']:
            assert any(c['kind'] == 'uncertainty' and c['support_status'] == 'unknown' and not c['evidence'] and
                       (c['assertion']['subject'], c['assertion']['predicate']) == (requirement['subject'], requirement['predicate'])
                       for c in claims), 'missing uncertainty'
    for path in [C, EXERCISES / MANIFEST['variants'][2]['path']]:
        reference = read(path / 'reference.json')
        examples = read(path / 'examples.json')
        for group in examples.values():
            for example in group: invoke('validate','claims',example['value'])
        for example in examples['positive']:
            complete(example,reference)
            no_uncertainty = copy.deepcopy(example)
            no_uncertainty['value']['claims'] = [c for c in no_uncertainty['value']['claims'] if c['kind'] != 'uncertainty']
            with pytest.raises(AssertionError,match='missing uncertainty'): complete(no_uncertainty,reference)
            no_rows = copy.deepcopy(example)
            next(c for c in no_rows['value']['claims'] if c['reference_fact_ids'] == ['C-percent'])['evidence'] = []
            with pytest.raises(AssertionError,match='missing evidence'): complete(no_rows,reference)
        for example in examples['negative']:
            with pytest.raises((AssertionError,ValueError)): complete(example,reference)
