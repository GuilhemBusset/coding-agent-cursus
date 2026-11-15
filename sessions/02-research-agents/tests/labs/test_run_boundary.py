"""Offline CLI integration of immutable versions and pinned public grading."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

SESSION = Path(__file__).resolve().parents[2]
FIXED = SESSION / 'exercises/fixed'
EXPORT = FIXED / 'runtime/fixtures/rating-support.zip'


def cli(module, *args, env=None):
    return subprocess.run([sys.executable, '-m', 'exercises.fixed.' + module, *map(str, args)],
                          cwd=SESSION, env=env, capture_output=True, text=True, timeout=45)


def ok(result):
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def put(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')


@pytest.fixture(scope='session')
def installed():
    # Fresh verifier copies install from the session lock, never global modules.
    if not (SESSION / 'node_modules/@earendil-works/pi-ai/package.json').exists():
        npm = shutil.which('npm')
        assert npm, 'session setup requires npm'
        result = subprocess.run([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], cwd=SESSION,
                                capture_output=True, text=True, timeout=180)
        print(result.stdout, result.stderr)
        assert result.returncode == 0
    return True


@pytest.fixture
def lab(installed):
    with TemporaryDirectory(prefix='s2-tests-') as temporary:
        tmp = Path(temporary)
        root = tmp / 'student work with spaces/exercises'
        (root / 'harness').mkdir(parents=True)
        (root / 'prompts').mkdir()
        (root / 'prompts/system.md').write_text('PROMPT_SENTINEL: inspect evidence.', encoding='utf-8')
        cache = tmp / 'offline cache'
        ok(cli('run', 'prepare', '--cache', cache, '--export', EXPORT))
        try:
            yield dict(root=root, cache=cache, options=load(FIXED / 'config/run.v1.json'), tmp=tmp)
        finally:
            for status in sorted((root / 'runs').glob('*/runtime-status.json')):
                print(status.parent.name, status.read_text(encoding='utf-8'))


def snapshot(lab, source, name='candidate-v1'):
    (lab['root'] / 'harness/main.ts').write_text(source, encoding='utf-8')
    saved = lab['tmp'] / ('saved ' + name)
    ok(cli('snapshot', '--exercises', lab['root'], '--name', name, '--output', saved))
    return saved


def usage(i=100, o=20, cached=10, reasoning=2):
    return dict(input_tokens=i, output_tokens=o, total_tokens=i + o,
                input_tokens_details=dict(cached_tokens=cached, cache_write_tokens=0),
                output_tokens_details=dict(reasoning_tokens=reasoning))


def response(calls=(), text='research response', tokens='default', failed=False):
    """Independent provider SSE consumed through the actual Pi adapter."""
    tokens = usage() if tokens == 'default' else tokens
    events: list[dict[str, Any]] = [dict(type='response.created', response=dict(id='resp_offline'))]
    items: list[dict[str, Any]] = []
    item: dict[str, Any]
    for index, (name, args) in enumerate(calls):
        item = dict(type='function_call', id=f'fc_{index}', call_id=f'call_{index}', name=name, arguments=json.dumps(args))
        items.append(item)
        events += [dict(type='response.output_item.added', output_index=index, item=dict(item, arguments='')),
                   dict(type='response.function_call_arguments.delta', output_index=index, delta=item['arguments']),
                   dict(type='response.function_call_arguments.done', output_index=index, arguments=item['arguments']),
                   dict(type='response.output_item.done', output_index=index, item=item)]
    if text and not failed and not calls:
        item = dict(type='message', id='msg_offline', role='assistant', content=[dict(type='output_text', text=text, annotations=[])])
        items.append(item)
        events += [dict(type='response.output_item.added', output_index=0, item=dict(item, content=[])),
                   dict(type='response.output_text.delta', output_index=0, content_index=0, delta=text),
                   dict(type='response.output_item.done', output_index=0, item=item)]
    events.append(dict(type='response.failed' if failed else 'response.completed',
                       response=dict(id='resp_offline', status='failed' if failed else 'completed', output=items,
                                     usage=tokens, error=dict(message='synthetic failure') if failed else None)))
    return dict(body=''.join('data: ' + json.dumps(e) + '\n\n' for e in events))


def launch(lab, saved, steps, name='attempt', env=None, options=None, mode='rating'):
    script = lab['tmp'] / (name + '-transport.json')
    put(script, steps)
    config = lab['tmp'] / (name + '-settings.json')
    put(config, options or lab['options'])
    ok(cli('run', 'run', '--snapshot', saved, '--exercises', lab['root'], '--cache', lab['cache'],
           '--script', script, '--settings', config, '--name', name, '--mode', mode, env=env))
    out = lab['root'] / 'runs' / name
    return out, load(out / 'runtime-status.json')


def trace(out):
    return [json.loads(s) for s in (out / 'trace.jsonl').read_text(encoding='utf-8').splitlines()]


def test_snapshot_integrity(lab):
    saved = snapshot(lab, 'export async function run(api) { await api.model(); }')
    before = {p.relative_to(saved): p.read_bytes() for p in saved.rglob('*') if p.is_file()}
    (lab['root'] / 'harness/main.ts').write_text('throw Error("edited")', encoding='utf-8')
    (lab['root'] / 'prompts/system.md').write_text('edited prompt', encoding='utf-8')
    assert before == {p.relative_to(saved): p.read_bytes() for p in saved.rglob('*') if p.is_file()}
    for group, files in load(saved / 'snapshot.json')['files'].items():
        for name, sha in files.items():
            assert hashlib.sha256((saved / group / name).read_bytes()).hexdigest() == sha
    assert cli('snapshot', '--exercises', lab['root'], '--name', 'candidate-v1', '--output', saved).returncode == 2
    (saved / 'prompts/system.md').write_text('tampered', encoding='utf-8')
    script = lab['tmp'] / 'unused.json'
    put(script, [response()])
    rejected = cli('run', 'run', '--snapshot', saved, '--cache', lab['cache'], '--exercises', lab['root'], '--script', script)
    assert rejected.returncode == 2 and 'snapshot digest mismatch' in rejected.stderr
    assert not (lab['root'] / 'runs').exists()


def test_fresh_runs_and_saved_versions(lab):
    saved = snapshot(lab, '''
import { existsSync, writeFileSync } from 'node:fs';
let conversation = [];
export async function run(api) {
  if (existsSync('prior-file') || conversation.length || process.env.FIRST_RUN_MARKER || process.env.OPENAI_API_KEY || process.env.COURSE_ENDPOINT_OPENAI) throw Error('leak');
  writeFileSync('prior-file', 'prior-state'); conversation.push('prior-conversation');
  process.env.FIRST_RUN_MARKER = 'private-configuration'; await api.model();
}''')
    options = dict(lab['options'], budgets=dict(model_attempts=1, tool_invocations=1, total_tokens=30000))
    first, _ = launch(lab, saved, [response(text='first-run-private-result')], 'first', options=options)
    (lab['root'] / 'harness/main.ts').write_text('throw Error("edited")', encoding='utf-8')
    (lab['root'] / 'prompts/system.md').write_text('edited prompt', encoding='utf-8')
    second, status = launch(lab, saved, [response(text='second-result')], 'second')
    assert status['detail'] == 'no_progress'
    assert load(first / 'accounting.json')['model_attempts'] == load(second / 'accounting.json')['model_attempts'] == 1
    assert load(second / 'config.json')['budgets']['model_attempts'] == 12
    captured = (second / 'requests.jsonl').read_text(encoding='utf-8')
    assert 'PROMPT_SENTINEL' in captured
    assert all(s not in captured for s in ['first-run-private-result', 'prior-conversation', 'edited prompt', 'private-configuration'])
    assert load(first / 'config.json')['workspace']['workspace_id'] != load(second / 'config.json')['workspace']['workspace_id']
    assert cli('run', 'run', '--snapshot', saved, '--exercises', lab['root'], '--cache', lab['cache'],
               '--script', lab['tmp'] / 'second-transport.json', '--name', 'second').returncode == 2


def test_public_bundle_preparation_and_development(lab):
    pin = load(FIXED / 'config/rating-bundle.v1.json')
    files = load(FIXED / 'config/rating-files.v1.json')['files']
    assert len(pin['revision']) == 40 and not pin['illustrative']
    assert hashlib.sha256((FIXED / 'config/rating-files.v1.json').read_bytes()).hexdigest() == pin['sha256']
    for name, sha in files.items():
        assert hashlib.sha256((lab['cache'] / name).read_bytes()).hexdigest() == sha
    ok(cli('run', 'prepare', '--cache', lab['tmp'] / 'second cache', '--export', lab['cache']))
    shutil.copytree(lab['cache'] / 'exercises/fixed', lab['root'] / 'fixed')
    shutil.copytree(lab['cache'] / 'exercises/cases', lab['root'] / 'cases')
    path = lab['root'] / 'cases/a-find/case.json'
    edited = load(path)
    edited['question'] = 'DEVELOPMENT_QUESTION'
    put(path, edited)
    saved = snapshot(lab, 'export async function run(api) { await api.model(); }')
    out, _ = launch(lab, saved, [response()], mode='development')
    assert load(out / 'run-inputs.json')['mode'] == 'development'
    assert load(out / 'config.json')['rating_bundle']['revision'] == 'development-working-tree'
    assert 'DEVELOPMENT_QUESTION' in (out / 'requests.jsonl').read_text(encoding='utf-8')


def test_rating_ignores_local_case_reference_and_evaluator(lab):
    fixtures = lab['cache'] / 'exercises/fixed/grading/fixtures/pass-A'
    output = dict(claims=load(fixtures / 'claims.json')['claims'], claim_anchors=load(fixtures / 'report.json')['claim_anchors'],
                  markdown=(fixtures / 'report.md').read_text(encoding='utf-8'), model_attempts=0, total_tokens=0, quality_pass=False)
    saved = snapshot(lab, 'export async function run(api) { await api.model(); return ' + json.dumps(output) + '; }')
    for name in ['cases/a-find/case.json', 'cases/a-find/reference.json', 'fixed/grading/engine.py']:
        path = lab['root'] / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('LOCAL_REFERENCE_RUBRIC_SENTINEL edited local support', encoding='utf-8')
    out, status = launch(lab, saved, [response()])
    assert status['detail'] == 'completed'
    score = load(out / 'scorecard.json')
    assert score['quality_pass'] and score['model_attempts'] == 1 and score['total_tokens'] == 120
    capture = (out / 'requests.jsonl').read_text(encoding='utf-8')
    assert 'Which methods' in capture and 'LOCAL_REFERENCE_RUBRIC_SENTINEL' not in capture
    assert all(s not in capture for s in ['reference_path', 'accepted_evidence', 'grading_assertions'])
    assert (lab['cache'] / 'exercises/cases/a-find/reference.json').is_file()
    for failure in ['missing', 'digest mismatch']:
        path = lab['cache'] / 'exercises/fixed/grading/engine.py'
        if failure == 'missing':
            path.unlink()
        else:
            path.write_text('altered evaluator', encoding='utf-8')
        rejected = cli('run', 'run', '--snapshot', saved, '--exercises', lab['root'], '--cache', lab['cache'],
                       '--script', lab['tmp'] / 'attempt-transport.json', '--name', 'rejected')
        assert rejected.returncode == 2 and 'rating bundle ' + failure in rejected.stderr
        assert not (lab['root'] / 'runs/rejected').exists()


def test_offline_smoke_context_and_sanitized_artifacts(lab):
    secret = 'sk-runtime-SENTINEL_credential'
    env = dict(os.environ, OPENAI_API_KEY=secret, COURSE_ENDPOINT_OPENAI='https://runtime.example/v1', UNDOCUMENTED_SENTINEL='private')
    saved = snapshot(lab, 'export async function run(api) { await api.model(); await api.tools(); await api.model(); }')
    out, status = launch(lab, saved, [response([('search', dict(query='shared charger', limit=1))]),
                                    response(text=secret + ' Bearer header-secret https://user:password@host/?key=query-secret')], env=env)
    assert status['detail'] == 'no_progress'
    requests = [json.loads(s)['body'] for s in (out / 'requests.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(requests) == 2 and [t['name'] for t in requests[0]['tools']] == ['read', 'search']
    assert 'PROMPT_SENTINEL' in json.dumps(requests[0]) and 'Which methods' in json.dumps(requests[0])
    assert 'function_call_output' in json.dumps(requests[1]) and 'source_id' in json.dumps(requests[1])
    for forbidden in ['accepted_evidence', 'reference_path', 'grading_assertions', 'UNDOCUMENTED_SENTINEL']:
        assert forbidden not in json.dumps(requests)
    for path in out.rglob('*'):
        if path.is_file():
            assert all(s not in path.read_text(encoding='utf-8') for s in [secret, 'header-secret', 'user:password', 'query-secret', 'runtime.example'])
    print('Synthetic offline smoke; pinned revision:', load(out / 'config.json')['rating_bundle']['revision'])
    print('Representative sanitized config:', (out / 'config.json').read_text(encoding='utf-8'))
    print('Representative sanitized trace:', (out / 'trace.jsonl').read_text(encoding='utf-8'))
