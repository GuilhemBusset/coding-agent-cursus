"""Public fault execution and honest replay through the real event/grading pipeline."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

SESSION = Path(__file__).resolve().parents[2]
FIXED = SESSION / 'exercises/fixed'
FIXTURES = FIXED / 'fixtures/faults'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(root):
    return {str(p.relative_to(root)): sha(p) for p in root.rglob('*') if p.is_file()}


def cli(module, *args, deny_network=False):
    program = '''
import runpy, socket, subprocess, sys, urllib.request
if sys.argv.pop(1) == 'deny':
    def denied(*a, **k): raise AssertionError('network or child process attempted during replay')
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    urllib.request.urlopen = denied
    subprocess.Popen = denied
module = sys.argv.pop(1)
runpy.run_module('exercises.fixed.' + module, run_name='__main__')
'''
    env = {k: v for k, v in os.environ.items() if not any(s in k for s in ('API_KEY', 'COURSE_ENDPOINT', 'TOKEN'))}
    result = subprocess.run([sys.executable, '-c', program, 'deny' if deny_network else 'allow', module, *map(str, args)],
        cwd=SESSION, env=env, capture_output=True, text=True, timeout=60)
    return result


def ok(result):
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope='module')
def runtime():
    # Acceptance subprocesses use the session's pinned Node and lockfile.
    node = subprocess.run(['node', '--version'], capture_output=True, text=True, check=True)
    assert node.stdout.strip() == 'v24.15.0', 'use mise exec -- uv run --locked pytest ...'
    npm = shutil.which('npm')
    assert npm
    if not (SESSION / 'node_modules/@earendil-works/pi-ai/package.json').exists():
        installed = subprocess.run([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], cwd=SESSION,
            capture_output=True, text=True, timeout=180)
        print(installed.stdout, installed.stderr)
        assert installed.returncode == 0


SCENARIOS = [s['scenario_id'] for s in read(FIXED / 'config/public/manifest.json')['fault_scenarios']]
EXPECTED = read(FIXED / 'fixtures/expected.json')['scenarios']


@pytest.mark.parametrize('name', SCENARIOS)
def test_fault_execution(runtime, name):
    before = tree(SESSION / 'exercises/cases')
    policy = sha(FIXED / 'config/policy.v1.json')
    spec = read(FIXED / 'config/public/faults' / (name + '.json'))
    with TemporaryDirectory(prefix='s2-fault-proof-') as temporary:
        root = Path(temporary)
        traces = []
        for index in range(2):
            out = root / str(index)
            status = ok(cli('faults', '--scenario', name, '--out', out))
            print(name, status)
            config, score = read(out / 'config.json'), read(out / 'scorecard.json')
            assert {k: score[k] for k in EXPECTED[name]} == EXPECTED[name]
            assert config['evidence_kind'] == status['evidence_kind'] == 'synthetic'
            assert config['budgets'] == read(FIXED / 'config/policy.v1.json')['budgets']
            selected = read(FIXED / 'config/public/manifest.json')['variants'][2 if name == 'absent-usage' else 0]
            assert (config['seed'], config['variant_id'], config['case_id']) == (selected['seed'], selected['variant_id'], selected['case_id'])
            assert config['fault']['schedule']['trigger'] == spec['trigger']
            assert config['fault']['schedule']['responses'] == spec['responses']
            events = lines(out / 'trace.jsonl')
            assert events[0]['type'] == 'fault_activation' and events[0]['point'] == 'configured'
            assert all(e['schedule'] == config['fault']['schedule'] for e in events if e['type'] == 'fault_activation')
            attempts = [e for e in events if e['type'] == 'model_attempt']
            tools = [e for e in events if e['type'] == 'tool_invocation']
            dispatches = lines(out / 'dispatches.jsonl')
            assert len(dispatches) == len(attempts) + len(tools)
            if name in ('timeout', 'rate-limit'):
                assert [a['error']['code'] for a in attempts] == [spec['responses'][0]['error']['code']] * 2
                assert attempts[1]['retry_of'] == attempts[0]['attempt_id']
                assert attempts[1]['request_id'] == attempts[0]['request_id']
                assert all(a['usage']['status'] == 'unknown' for a in attempts)
                if name == 'timeout':
                    assert all(a['status'] == 'cancelled' for a in attempts)
            if name == 'transient-read':
                assert tools[0]['result']['error'] == dict(code='service_error', retryable=True)
                assert tools[1]['retry_of'] == tools[0]['tool_call_id']
            if name in ('transient-read', 'repeated-retrieval', 'tool-budget'):
                good = [t for t in tools if t['result']['status'] == 'ok']
                corpus = read(SESSION / 'exercises' / selected['path'] / 'corpus.json')
                source = next(s for s in corpus['sources'] if s['passages'])
                passage = source['passages'][0]
                for tool in good:
                    assert tool['input']['arguments'] == dict(source_id=source['source_id'], start=passage['start'], end=passage['end'])
                    assert passage['quote'] in json.dumps(tool['result'], ensure_ascii=False)
                if name == 'repeated-retrieval':
                    assert len({json.dumps(t['result']['data'], sort_keys=True) for t in good}) == 1
            if name in ('missing-source', 'malformed-tool-arguments'):
                assert tools[0]['result']['error']['code'] == ('not_found' if name == 'missing-source' else 'invalid_input')
                if name == 'malformed-tool-arguments':
                    assert tools[0]['input']['rejected'] is True
                    assert tools[0]['input']['arguments'] == spec['trigger']['arguments']
            if name == 'malformed-output':
                assert read(out / 'candidate-output.json')['raw_output'] == spec['responses'][0]['raw_output']
            if name.endswith('-budget'):
                counter = spec['trigger']['counter']
                assert score[counter] == spec['trigger']['value']
                if name == 'token-budget':
                    reservations = lines(out / 'reservations.jsonl')
                    assert reservations[0]['reserved_tokens'] == 30000 and reservations[0]['admitted']
                    assert reservations[-1]['observed_tokens_before'] == 30000 and not reservations[-1]['admitted']
            # Fresh envelopes and wall time vary; fault payloads, linkage and counts do not.
            for event in events:
                for key in ('run_id', 'elapsed_ms', 'duration_ms'):
                    event.pop(key, None)
                if event['type'] == 'tool_invocation':
                    for key in ('input', 'result'):
                        event[key].pop('run_id')
            traces.append(events)
        assert traces[0] == traces[1]
    assert before == tree(SESSION / 'exercises/cases') and policy == sha(FIXED / 'config/policy.v1.json')


@pytest.mark.parametrize('name', SCENARIOS)
def test_published_replay_offline(name):
    source = FIXTURES / name
    before = tree(source)
    with TemporaryDirectory(prefix='s2-replay-proof-') as temporary:
        out = Path(temporary) / 'offline output'
        result = ok(cli('replay', '--run', source, '--out', out, deny_network=True))
        print(name, result)
        assert result['evidence_kind'] == 'replay' and result['source_evidence_kind'] == 'synthetic'
        score = read(out / 'scorecard.json')
        assert {k: score[k] for k in EXPECTED[name]} == EXPECTED[name]
        assert score['evidence_kind'] == 'replay'
        config, original = read(out / 'config.json'), read(source / 'config.json')
        assert config['run_id'] != original['run_id'] and config['replay_of'] == original['run_id']
        assert config['workspace']['workspace_id'] != original['workspace']['workspace_id']
        assert read(out / 'accounting.json') == read(source / 'accounting.json')
        assert (out / 'source-trace.jsonl').read_bytes() == (source / 'trace.jsonl').read_bytes()
        assert (out / 'source-config.json').read_bytes() == (source / 'config.json').read_bytes()
        provenance = read(out / 'provenance.json')
        assert provenance['source_trace_sha256'] == sha(source / 'trace.jsonl')
        assert provenance['source_config_sha256'] == sha(source / 'config.json')
        assert {'grading.json', 'peer-review.md', 'efficiency.json', 'claims.json', 'report.json', 'report.md', 'policy.json'} <= {p.name for p in out.iterdir()}
    assert before == tree(source)


@pytest.mark.parametrize('damage', ['truncated-json', 'missing-terminal', 'corrupted-content', 'wrong-config-hash'])
def test_replay_rejects_damage(damage):
    with TemporaryDirectory(prefix='s2-corrupt-proof-') as temporary:
        source = Path(temporary) / 'source'
        shutil.copytree(FIXTURES / 'transient-read', source)
        trace = source / 'trace.jsonl'
        if damage == 'truncated-json':
            trace.write_text(trace.read_text()[:-15], encoding='utf-8')
        elif damage == 'missing-terminal':
            trace.write_text('\n'.join(trace.read_text().splitlines()[:-1]) + '\n', encoding='utf-8')
            # Even a resealed digest cannot make an incomplete event stream valid.
            p = read(source / 'provenance.json')
            p['files']['trace.jsonl'] = sha(trace)
            (source / 'provenance.json').write_text(json.dumps(p), encoding='utf-8')
        elif damage == 'corrupted-content':
            trace.write_text(trace.read_text().replace('service_error', 'timeout'), encoding='utf-8')
        else:
            p = read(source / 'provenance.json')
            p['files']['config.json'] = '0' * 64
            (source / 'provenance.json').write_text(json.dumps(p), encoding='utf-8')
        out = Path(temporary) / 'rejected'
        result = cli('replay', '--run', source, '--out', out, deny_network=True)
        assert result.returncode == 2 and not out.exists(), result.stdout + result.stderr


def test_unknown_usage_and_live_evidence_rejection():
    with TemporaryDirectory(prefix='s2-unknown-proof-') as temporary:
        out = Path(temporary) / 'unknown'
        result = ok(cli('replay', '--run', FIXTURES / 'absent-usage', '--out', out, deny_network=True))
        assert result['total_tokens'] is None and result['efficiency_status'] == 'unknown_usage'
        efficiency = read(out / 'efficiency.json')
        assert efficiency['tokens_per_success'] is None and efficiency['successes'] == 1
        assert read(out / 'scorecard.json')['usage']['input_tokens'] is None
        assert cli('replay', '--run', FIXTURES / 'absent-usage', '--out', Path(temporary) / 'live', '--evidence-kind', 'captured_live').returncode == 2
        # Actual comparison admission must reject a replay against captured-live controls.
        program = '''
import json, sys
from pathlib import Path
from exercises.fixed import evaluate
from exercises.fixed.run import read
out = Path(sys.argv[1]); config = read(out / 'config.json')
shared = dict(settings=read(Path(sys.argv[2]) / 'config/run.v1.json'), support_files={},
              rating_bundle=config['rating_bundle'], mode=config['mode'], evidence_kind='captured_live')
slot = dict(case='c-audit/variants/public-seed-20261135', tools=['read', 'search', 'check_table'],
            **{k:config[k] for k in ('case_id','variant_id','seed','trial')})
saved = dict(snapshot_id=config['snapshot_id'], files=dict(harness={}, prompts={}))
try: evaluate.check_attempt(out, shared, slot, saved)
except ValueError as error:
    assert 'evidence_kind' in str(error), error
    print(str(error))
else: raise AssertionError('replay admitted as live evidence')
'''
        checked = subprocess.run([sys.executable, '-c', program, str(out), str(FIXED)], cwd=SESSION,
            capture_output=True, text=True, timeout=30)
        assert checked.returncode == 0, checked.stdout + checked.stderr
        print(checked.stdout)
