"""Run real Pi checkpoints through scripted Responses and supplied public tools."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
from test_contracts import invoke

SESSION = Path(__file__).resolve().parents[2]
FIXED = SESSION / 'exercises/fixed'
CHECKPOINTS = FIXED / 'checkpoints'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def journal(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def cli(module, *args):
    result = subprocess.run([sys.executable, '-m', 'exercises.fixed.' + module, *map(str, args)],
                            cwd=SESSION, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope='module', autouse=True)
def dependencies():
    if not (SESSION / 'node_modules/@earendil-works/pi-agent-core/package.json').exists():
        npm = shutil.which('npm')
        assert npm, 'install the session pinned runtime first'
        result = subprocess.run([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'],
                                cwd=SESSION, capture_output=True, text=True, timeout=180)
        print(result.stdout, result.stderr)
        assert result.returncode == 0


@pytest.fixture
def student():
    with TemporaryDirectory(prefix='s2-checkpoints-') as temporary:
        root = Path(temporary) / 'student workspace with spaces/exercises'
        root.mkdir(parents=True)
        try:
            yield root
        finally:
            for path in root.glob('runs/*/runtime-status.json'):
                print(path.parent.name, path.read_text(encoding='utf-8'))


def checked(output, attempts, tools):
    events = journal(output / 'trace.jsonl')
    config = load(output / 'config.json')
    for kind, name in [('run-config', 'config'), ('claims', 'claims'), ('report', 'report'), ('scorecard', 'scorecard')]:
        invoke('validate', kind, load(output / (name + '.json')))
    for event in events:
        invoke('validate', 'trace-event', event)
    accounting = invoke('summarize_trace', events, config['run_id'])
    assert accounting == load(output / 'accounting.json')
    assert accounting['model_attempts'] == attempts
    assert accounting['tool_invocations'] == tools
    assert accounting['total_tokens'] == attempts * 120
    assert not accounting['intervention']
    assert config['evidence_kind'] == 'synthetic' and config['workspace']['fresh']
    assert load(output / 'scorecard.json')['output_valid']
    assert load(output / 'runtime-status.json')['stop_reason'] == 'completed'
    return [row['body'] for row in journal(output / 'requests.jsonl')]


def completed(student, checkpoint):
    cli('checkpoint', 'rejoin', checkpoint, '--exercises', student)
    result = cli('checkpoint', 'run', checkpoint, '--offline', '--exercises', student)
    return Path(result['output']), result


def test_model_baseline(student):
    output, result = completed(student, '00-model')
    requests = checked(output, 1, 0)
    assert not requests[0].get('tools')
    assert 'Which methods' in json.dumps(requests[0])
    comparison = load(output / 'checkpoint-comparison.json')
    reference = load(Path(comparison['reference']))
    assert reference['case_id'] == 'A'
    assert comparison['required_facts_total'] > 0
    assert comparison['failed_assertion_ids'] == load(output / 'scorecard.json')['failed_assertion_ids']
    saved = Path(result['snapshot'])
    original = (saved / 'harness/main.ts').read_bytes()
    (student / 'harness/main.ts').write_text('student later edit', encoding='utf-8')
    assert (saved / 'harness/main.ts').read_bytes() == original
    assert (output / 'report.md').is_file()
    assert all(word not in json.dumps(requests) for word in ('accepted_evidence', 'grading_assertions', 'reference_path'))


def test_read_returns_evidence(student):
    output, _ = completed(student, '01-read')
    requests = checked(output, 2, 1)
    assert [tool['name'] for tool in requests[0]['tools']] == ['read']
    event = next(e for e in journal(output / 'trace.jsonl') if e['type'] == 'tool_invocation')
    assert event['input']['arguments']['source_id'] == 'EV-S01'
    assert event['result']['status'] == 'ok'
    source = (SESSION / 'exercises/cases/a-find/sources/EV-S01.md').read_text(encoding='utf-8')
    # Assert actual returned evidence is fed to the model, not just a tool counter.
    outputs = [item['output'] for item in requests[1]['input'] if item.get('type') == 'function_call_output']
    assert any(source in json.dumps(json.loads(text), ensure_ascii=False).replace('\\n', '\n') for text in outputs)


def response(turn, name=None, arguments=None):
    """Independent synthetic provider messages, not the checkpoint answer fixtures."""
    events: list[dict[str, Any]]
    if name:
        item = dict(type='function_call', id=f'fc_{turn}', call_id=f'call_{turn}', name=name,
                    arguments=json.dumps(arguments))
        events = [dict(type='response.output_item.added', output_index=0, item=dict(item, arguments='')),
                  dict(type='response.function_call_arguments.delta', output_index=0, delta=item['arguments']),
                  dict(type='response.output_item.done', output_index=0, item=item)]
    else:
        claim = dict(claim_id='unknown', kind='uncertainty', support_status='unknown', evidence=[],
                     assertion=dict(subject='shared-methods', predicate='performance_under_uncertain_demand',
                                    type='string', value='unknown', unit=None),
                     reference_fact_ids=[], experiment_ids=[], supersedes_claim_ids=[])
        answer = dict(claims=[claim], claim_anchors=[dict(claim_id='unknown', anchor='claim-unknown')],
                      markdown='<a id="claim-unknown"></a>\nSynthetic smoke: uncertain-demand performance is unknown.')
        text = json.dumps(answer)
        item = dict(type='message', id=f'msg_{turn}', role='assistant', content=[dict(type='output_text', text=text, annotations=[])])
        events = [dict(type='response.output_item.added', output_index=0, item=dict(item, content=[])),
                  dict(type='response.output_text.delta', output_index=0, content_index=0, delta=text),
                  dict(type='response.output_item.done', output_index=0, item=item)]
    usage = dict(input_tokens=100, output_tokens=20, total_tokens=120,
                 input_tokens_details=dict(cached_tokens=0), output_tokens_details=dict(reasoning_tokens=0))
    events.append(dict(type='response.completed', response=dict(id=f'resp_{turn}', status='completed', output=[item], usage=usage)))
    return dict(body=''.join('data: ' + json.dumps(event) + '\n\n' for event in events))


@pytest.mark.parametrize(('query', 'source_id'), [('Slot Ledger', 'EV-S02'), ('Queue Repair', 'EV-S03')])
def test_search_uses_model_selected_source(student, query, source_id):
    cli('checkpoint', 'rejoin', '02-search', '--exercises', student)
    snapshot = student / 'runs/versions/choice'
    cli('snapshot', '--exercises', student, '--name', 'choice', '--output', snapshot)
    cache = student / 'runs/cache'
    cli('run', 'prepare', '--cache', cache, '--export', FIXED / 'runtime/fixtures/rating-support.zip')
    script = student / 'provider.json'
    script.write_text(json.dumps([response(1, 'read', dict(source_id='EV-S01')),
                                 response(2, 'search', dict(query=query, limit=8)),
                                 response(3, 'read', dict(source_id=source_id)), response(4)]), encoding='utf-8')
    cli('run', 'run', '--snapshot', snapshot, '--exercises', student, '--cache', cache,
        '--script', script, '--tools', 'read,search', '--name', 'chosen')
    output = student / 'runs/chosen'
    requests = checked(output, 4, 3)
    assert [t['name'] for t in requests[0]['tools']] == ['read', 'search']
    invocations = [e for e in journal(output / 'trace.jsonl') if e['type'] == 'tool_invocation']
    assert [e['input']['tool'] for e in invocations] == ['read', 'search', 'read']
    assert source_id in json.dumps(invocations[1]['result'])
    assert invocations[2]['input']['arguments']['source_id'] == source_id
    assert invocations[2]['result']['status'] == 'ok'
    returned = [json.loads(i['output']) for i in requests[-1]['input'] if i.get('type') == 'function_call_output']
    assert invocations[0]['result'] in returned and invocations[2]['result'] in returned


def test_rejoin_preserves_both_directories(student):
    saved_backups = []
    for index, checkpoint in enumerate(('00-model', '01-read', '02-search')):
        expected = {}
        for group in ('harness', 'prompts'):
            path = student / group / 'nested/my edits.txt'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f'{group} edits {index}\r\n'.encode())
            expected[group] = {p.relative_to(student / group): p.read_bytes() for p in (student / group).rglob('*') if p.is_file()}
        result = cli('checkpoint', 'rejoin', checkpoint, '--exercises', student)
        backup = Path(result['backup'])
        assert backup not in [path for path, _ in saved_backups]
        saved_backups.append((backup, expected))
        for group in ('harness', 'prompts'):
            entry = 'main.ts' if group == 'harness' else 'system.md'
            assert (student / group / entry).exists()
            assert not (student / group / 'nested/my edits.txt').exists()
        for prior, contents in saved_backups:
            for group, files in contents.items():
                assert files == {p.relative_to(prior / group): p.read_bytes() for p in (prior / group).rglob('*') if p.is_file()}


@pytest.mark.parametrize(('checkpoint', 'attempts', 'tools'), [('00-model', 1, 0), ('01-read', 2, 1), ('02-search', 4, 3)])
def test_completed_checkpoints_run_fresh(student, checkpoint, attempts, tools):
    output, _ = completed(student, checkpoint)
    checked(output, attempts, tools)
    assert load(output / 'config.json')['case_id'] == 'A'
    assert load(output / 'config.json')['variant_id'] == 'base'
    # Also run the actual documented restore/run sequence a second time.
    second, _ = completed(student, checkpoint)
    checked(second, attempts, tools)
    assert output != second
    assert load(output / 'config.json')['workspace']['workspace_id'] != load(second / 'config.json')['workspace']['workspace_id']
