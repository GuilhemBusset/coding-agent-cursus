"""Exercise the public runtime against evidence only, with independent numeric oracles."""

import csv
import io
import json
import shutil
import subprocess
import sys
import unicodedata
from decimal import Decimal
from pathlib import Path

import pytest

SESSION = Path(__file__).resolve().parents[2]
# Match the other session suites: import the standalone package in a subprocess
# from the session root, without modifying Python's import path.
PROGRAM = """
import json, sys
from pathlib import Path
from exercises.fixed.bridge.dispatch import dispatch
from exercises.fixed.schemas.validate import validate
from exercises.fixed.tools.corpus import Corpus, ToolError
from exercises.fixed.tools.research import MAX_HITS, MAX_QUERY, MAX_READ, MAX_SNIPPET
request = json.load(sys.stdin)
root = Path(request['root'])
action = request['action']
payload = request['payload']
# Guard runtime data reads, including the reused CSV loader. Schema files are
# trusted implementation inputs. The copied bundles contain no answers at all.
original_open = Path.open
allowed = {root / 'corpus.json'} | set((root / 'sources').glob('*'))
schemas = Path('exercises/fixed/schemas').resolve()
def guarded(path, *args, **kwargs):
    assert path in allowed or path.resolve().is_relative_to(schemas), str(path)
    return original_open(path, *args, **kwargs)
Path.open = guarded
try:
    if action == 'limits':
        value = [MAX_HITS, MAX_QUERY, MAX_READ, MAX_SNIPPET]
    elif action == 'call':
        value = dispatch(root, payload)
        validate('tool-result', value['result'])
        if value['result']['status'] == 'ok':
            validate('tool-input', value['invocation'])
    else:
        corpus = Corpus(root)
        if action == 'sources':
            value = corpus.sources
        elif action == 'text':
            value = corpus.text(payload)
        elif action == 'passages':
            value = corpus.passages(payload)
        else:
            raise AssertionError('unknown test action')
    print(json.dumps({'value': value}))
except ToolError as error:
    print(json.dumps({'error': error.code}))
"""


def runtime(root, action, payload=None):
    result = subprocess.run([sys.executable, '-c', PROGRAM], cwd=SESSION,
                            input=json.dumps(dict(root=str(root), action=action, payload=payload)),
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr
    response = json.loads(result.stdout)
    if 'error' in response:
        raise ValueError(response['error'])
    return response['value']


class Corpus:
    def __init__(self, root):
        self.root = root
        self.sources = runtime(root, 'sources')

    def text(self, sid):
        return runtime(self.root, 'text', sid)

    def passages(self, sid):
        return runtime(self.root, 'passages', sid)


MAX_HITS, MAX_QUERY, MAX_READ, MAX_SNIPPET = runtime(SESSION / 'exercises/cases/c-audit', 'limits')

CASES = sorted((SESSION / 'exercises/cases').rglob('corpus.json'))


def bundle(manifest, target):
    target.mkdir(parents=True)
    shutil.copyfile(manifest, target / 'corpus.json')
    shutil.copytree(manifest.parent / 'sources', target / 'sources')
    return target


def call(root, tool, args):
    return runtime(root, 'call', dict(tool=tool, arguments=args, run_id='test-run', tool_call_id='call-1'))


def table_args(root):
    corpus = Corpus(root)
    source = next(s for s in corpus.sources.values() if s['path'].endswith('.csv'))
    rows = list(csv.DictReader(io.StringIO(corpus.text(source['source_id']))))
    methods = list(dict.fromkeys(r['method'] for r in rows))
    return dict(source_id=source['source_id'], method_left=methods[0], method_right=methods[1], metric='cost',
                unit=source['units']['cost'], feasible_only=True, pair_key='pair_id',
                pair_ids=sorted({r['pair_id'] for r in rows})), rows


@pytest.mark.parametrize('manifest', CASES, ids=lambda p: str(p.relative_to(SESSION / 'exercises/cases')))
def test_evidence_only_spans_search_and_order(manifest, tmp_path):
    root = bundle(manifest, tmp_path / 'evidence only')
    corpus = Corpus(root)
    for sid in corpus.sources:
        text = corpus.text(sid)
        end = min(len(text), 37)
        reply = call(root, 'read', dict(source_id=sid, start=1, end=end))
        assert reply['result']['data'] == dict(span=dict(source_id=sid, kind='passage', start=1, end=end), text=text[1:end])
        assert reply['audit']['truncated'] == (len(text) > end or 1 > 0)
        for passage in corpus.passages(sid):
            hits = call(root, 'search', dict(query=passage['quote'][:MAX_QUERY], limit=MAX_HITS))
            assert any(h['passage_id'] == passage['passage_id'] for h in hits['audit']['hits'])
    # These concepts cover A assumptions, B corrections, C the absent demand experiment.
    query = 'shared charger correction uncertain demand feasibility'
    first = call(root, 'search', dict(query=query))
    assert first == call(root, 'search', dict(query=query))
    data, audit = first['result']['data'], first['audit']
    assert data
    ordering = [(-h['score'], h['passage_span']['source_id'], h['passage_span']['start']) for h in audit['hits']]
    assert ordering == sorted(ordering)
    for hit, metadata in zip(data, audit['hits'], strict=True):
        s = hit['span']
        assert hit['text'] == corpus.text(s['source_id'])[s['start']:s['end']]
        assert len(hit['text']) <= MAX_SNIPPET
        assert metadata['passage_span']['start'] <= s['start'] < s['end'] <= metadata['passage_span']['end']
    limited = call(root, 'search', dict(query=query, limit=1))
    assert limited['result']['data'] == data[:1]
    assert limited['audit']['total_hits'] >= len(data)
    assert limited['audit']['truncated']
    assert call(root, 'search', dict(query='zzzznoevidencematches'))['result']['data'] == []
    document = json.loads((root / 'corpus.json').read_text())
    document['sources'].reverse()
    (root / 'corpus.json').write_text(json.dumps(document), encoding='utf-8')
    assert call(root, 'search', dict(query=query)) == first


@pytest.mark.parametrize('manifest', [p for p in CASES if 'c-audit' in p.parts])
def test_independent_paired_cost_calculation(manifest, tmp_path):
    root = bundle(manifest, tmp_path / 'numeric evidence')
    args, rows = table_args(root)
    groups = {}
    for position, row in enumerate(rows, 1):
        groups.setdefault((row['instance_id'], row['run_id']), []).append((position, row))
    included = [entry for group in groups.values() if len(group) == 2
                and {r['method'] for _, r in group} == {args['method_left'], args['method_right']}
                and all(r['feasible'] == 'true' for _, r in group) for entry in group]
    totals = [sum(Decimal(r['cost']) for _, r in included if r['method'] == method) for method in (args['method_left'], args['method_right'])]
    ratio = (totals[0] - totals[1]) / totals[0]
    reply = call(root, 'check_table', args)
    data, audit = reply['result']['data'], reply['audit']
    assert data['relative_reduction'] == pytest.approx(float(ratio))
    assert audit['baseline_total'] == audit['denominator'] == totals[0]
    assert audit['candidate_total'] == totals[1]
    assert audit['reduction_percent'] == pytest.approx(float(100 * ratio))
    assert data['left_mean'] == float(totals[0] / (len(included) // 2))
    assert data['right_mean'] == float(totals[1] / (len(included) // 2))
    assert {p[k] for p in data['pairs'] for k in ('left_row', 'right_row')} == {i for i, _ in included}
    assert set(audit['excluded_row_ids']) == {r['row_id'] for r in rows} - {r['row_id'] for _, r in included}
    assert {r['start'] for r in data['evidence']} == {i for i, _ in included}
    for p, identities in zip(data['pairs'], audit['pairs'], strict=True):
        for side in ('left', 'right'):
            row = rows[p[side + '_row'] - 1]
            assert identities[side + '_row_id'] == row['row_id']
            assert identities[side + '_experiment_id'] == row['experiment_id']
            assert p[side + '_value'] == int(row['cost'])
    subset = {**args, 'pair_ids': [data['pairs'][0]['pair_id']]}
    assert len(call(root, 'check_table', subset)['result']['data']['pairs']) == 1


@pytest.mark.parametrize('tool,args,code', [
    ('read', {'source_id': '../reference.json'}, 'invalid_input'),
    ('read', {'source_id': '/etc/passwd'}, 'invalid_input'),
    ('read', {'source_id': 'EV-S01'}, 'not_found'),
    ('read', {'source_id': 'EV-S13', 'start': -1, 'end': 5}, 'invalid_input'),
    ('read', {'source_id': 'EV-S13', 'start': 1}, 'invalid_input'),
    ('read', {'source_id': 'EV-S13', 'start': True, 'end': 5}, 'invalid_input'),
    ('read', {'source_id': 'EV-S13', 'start': 5, 'end': 3}, 'invalid_input'),
    ('read', {'source_id': 'EV-S13', 'start': 0, 'end': 99999}, 'invalid_input'),
    ('read', {'source_id': 'EV-S13', 'path': 'reference.json'}, 'invalid_input'),
    ('search', {'query': ''}, 'invalid_input'),
    ('search', {'query': 'a' * (MAX_QUERY + 1)}, 'invalid_input'),
    ('search', {'query': 'cost', 'limit': MAX_HITS + 1}, 'invalid_input'),
    ('search', {'query': 'cost', 'limit': True}, 'invalid_input'),
    ('search', {'query': ['cost']}, 'invalid_input'),
])
def test_typed_invalid_arguments(tool, args, code):
    reply = call(SESSION / 'exercises/cases/c-audit', tool, args)
    assert reply['result']['error'] == dict(code=code, retryable=False)
    assert reply['result']['data'] is None


@pytest.mark.parametrize('patch', [
    {'operation': "__import__('os').system('echo BAD')"}, {'source_id': 'EV-S13'},
    {'source_id': 'unknown'}, {'pair_ids': ['unknown']}, {'pair_ids': ['../../secret']},
    {'pair_ids': []}, {'pair_ids': ['EV-PAIR-0001'] * 2}, {'metric': 'eval(cost)'},
    {'unit': 'USD'}, {'feasible_only': False}, {'pair_key': 'row_id'}, {'method_right': 'anything'},
    {'rows': [999]},
])
def test_table_rejects_unsupported_arguments(patch):
    root = SESSION / 'exercises/cases/c-audit'
    args, _ = table_args(root)
    assert call(root, 'check_table', {**args, **patch})['result']['status'] == 'error'


@pytest.mark.parametrize('defect', ['duplicate', 'zero', 'no_pairs', 'row_id', 'identity'])
def test_table_rejects_invalid_evidence(defect, tmp_path):
    root = bundle(SESSION / 'exercises/cases/c-audit/corpus.json', tmp_path / defect)
    args, rows = table_args(root)
    if defect == 'duplicate':
        rows[2].update(instance_id=rows[0]['instance_id'], run_id=rows[0]['run_id'], pair_id=rows[0]['pair_id'])
    elif defect == 'zero':
        for row in rows:
            if row['method'] == 'audit-a':
                row['cost'] = '0'
    elif defect == 'no_pairs':
        for row in rows:
            row['feasible'] = 'false'
    elif defect == 'row_id':
        rows[0]['row_id'] = 'EV-T01:R9999'
    else:
        rows[1]['instance_id'] = 'different'
    with (root / 'sources/EV-T01.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    assert call(root, 'check_table', args)['result']['error']['code'] == 'invalid_input'


@pytest.mark.parametrize('name', ['../reference.json', 'reference.json', '/etc/passwd', 'sources/../../secret.md', 'sources\\EV-S13.md'])
def test_manifest_traversal_rejected(name, tmp_path):
    root = bundle(SESSION / 'exercises/cases/c-audit/corpus.json', tmp_path / 'bad bundle')
    manifest = json.loads((root / 'corpus.json').read_text())
    manifest['sources'][0]['path'] = name
    (root / 'corpus.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='invalid_input'):
        Corpus(root)


def test_symlink_escape_rejected(tmp_path):
    root = bundle(SESSION / 'exercises/cases/c-audit/corpus.json', tmp_path / 'bundle')
    outside = tmp_path / 'outside.md'
    outside.write_text('not evidence')
    source = root / 'sources/EV-S13.md'
    source.unlink()
    source.symlink_to(outside)
    with pytest.raises(ValueError, match='invalid_input'):
        Corpus(root)


def test_long_unicode_results_are_bounded(tmp_path):
    root = tmp_path / 'unicode'
    (root / 'sources').mkdir(parents=True)
    text = unicodedata.normalize('NFC', 'énergie 🚚\n' * 1000)
    (root / 'sources/doc.md').write_text(text, encoding='utf-8')
    (root / 'corpus.json').write_text(json.dumps({'sources': [dict(source_id='DOC', path='sources/doc.md', passages=[
        dict(passage_id='DOC:P1', start=0, end=len(text), quote=text)])]}), encoding='utf-8')
    reply = call(root, 'read', {'source_id': 'DOC'})
    assert reply['result']['data']['text'] == text[:MAX_READ]
    assert reply['audit']['truncated']
    reply = call(root, 'search', {'query': 'énergie'})
    assert reply['audit']['hits'][0]['truncated']
    assert len(reply['result']['data'][0]['text']) == MAX_SNIPPET
    assert call(root, 'read', dict(source_id='DOC', start=0, end=MAX_READ + 1))['result']['status'] == 'error'
