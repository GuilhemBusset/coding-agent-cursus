"""Synthetic evidence tests: real Pi, public tools, outbound payloads and grader."""

import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from test_research_tools import runtime
from test_retrieval_checkpoints import FIXED, SESSION, cli, journal, load, response

MEMORY = SESSION / 'exercises/harness/memory.ts'
PREFIX = 'Claim–passage memory\n'


@pytest.fixture(scope='module', autouse=True)
def dependencies():
    # The acceptance command uses mise to select the checked-in Node pin.
    if (SESSION / 'node_modules/@earendil-works/pi-agent-core/package.json').exists():
        return
    npm = shutil.which('npm')
    assert npm
    result = subprocess.run([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'],
                            cwd=SESSION, capture_output=True, text=True, timeout=180)
    print(result.stdout, result.stderr)
    assert result.returncode == 0


@pytest.fixture
def student():
    with TemporaryDirectory(prefix='s2-memory-') as temporary:
        root = Path(temporary) / 'workspace with spaces/exercises'
        root.mkdir(parents=True)
        yield root


def node_memory(reads, extra=''):
    script = f"""
import {{ createMemory, memoryLimits }} from {json.dumps(MEMORY.as_uri())};
const memory = createMemory();
const states = [];
for (const result of {json.dumps(reads)}) {{ memory.ingest(result); states.push(memory.snapshot()); }}
{extra}
console.log(JSON.stringify({{ states, fresh: createMemory().snapshot(), limits: memoryLimits }}));
"""
    result = subprocess.run(['node', '--input-type=module', '-'], input=script, cwd=SESSION,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def evidence(source_id):
    # Feed the actual public tool result, including its code-point spans.
    return runtime(SESSION / 'exercises/cases/b-compare', 'call',
                   dict(tool='read', arguments={'source_id': source_id}, run_id='memory-test', tool_call_id='tool-1'))['result']


def by_source(state, source_id):
    return [entry for entry in state['ledger'] if entry['passage_id'].split(':')[0] == source_id]


@pytest.mark.parametrize('order', [('EV-S05', 'EV-S06'), ('EV-S06', 'EV-S05')])
def test_accumulation_correction_and_unresolved(order):
    result = node_memory([evidence(source) for source in order])
    first, second = result['states']
    assert len(second['ledger']) == 3
    assert second['sources']['EV-S05']['conflict_status'] == 'superseded'
    assert second['sources']['EV-S05']['superseded_by'] == ['EV-S06']
    correction = by_source(second, 'EV-S06')[0]
    assert second['sources']['EV-S06']['conflict_status'] == 'correction'
    assert second['sources']['EV-S06']['supersedes'] == ['EV-S05']
    assert second['sources']['EV-S06']['date'] == '2026-10-12'
    assert '84 seconds' in correction['claim']
    pending = 'EV-S06' if order[0] == 'EV-S05' else 'EV-S05'
    assert pending in [q['source_id'] for q in first['unresolved']]
    assert pending not in [q['source_id'] for q in second['unresolved']]
    assert result['fresh']['ledger'] == [] and result['fresh']['unresolved'] == []
    # The ledger carries exact passage text at independently usable source spans.
    for entry in second['ledger']:
        source = (SESSION / 'exercises/cases/b-compare/sources' / (entry['passage_id'].split(':')[0] + '.md')).read_text()
        assert source[entry['span'][0]:entry['span'][1]] == entry['claim']


def test_duplicate_reports_and_bounded_overflow():
    result = node_memory([evidence(s) for s in ('EV-S07', 'EV-S08', 'EV-S09', 'EV-S10', 'EV-S07')])
    state = result['states'][-1]
    assert len(state['ledger']) == 5  # rereading the primary report adds nothing
    groups = {group['experiment_id']: group['passage_ids'] for group in state['experiments']}
    assert groups['EV-E-Q1'] == ['EV-S07:P01', 'EV-S08:P01', 'EV-S09:P01']
    assert groups['EV-E-Q2'] == ['EV-S10:P01', 'EV-S10:P02']
    # Unknown partial spans retain evidence without inventing parent metadata.
    partial = evidence('EV-S07')
    partial['data'] = dict(span=dict(source_id='EV-S07', kind='passage', start=400, end=405), text='hello')
    state = node_memory([partial])['states'][0]
    assert state['ledger'][0]['passage_id'] == 'EV-S07:400-405'
    assert state['sources']['EV-S07']['date'] is None and state['sources']['EV-S07']['experiment_ids'] == []
    assert state['unresolved'][0]['source_id'] == 'EV-S07'
    assert node_memory([evidence('EV-S07'), partial])['states'][-1]['sources']['EV-S07']['date'] == '2026-10-08'
    many = [dict(partial, data=dict(span=dict(source_id=f'X-{i}', kind='passage', start=0, end=1000), text='😀' * 1000))
            for i in range(90)]
    overflow = node_memory(many)['states'][-1]
    assert len(overflow['ledger']) <= result['limits']['entries']
    assert len(json.dumps(overflow, ensure_ascii=False, separators=(',', ':')).encode()) <= result['limits']['bytes']
    assert overflow['omitted_entries'] > 0
    assert any(q['kind'] == 'capacity' for q in overflow['unresolved'])
    assert node_memory([dict(partial, status='error', data=None)])['states'][-1]['ledger'] == []


def run(student, case):
    result = cli('checkpoint', 'run', '03-memory', '--case', case, '--offline', '--exercises', student)
    output = Path(result['output'])
    print(json.dumps({key: result[key] for key in ('run_id', 'quality_pass', 'model_attempts', 'total_tokens', 'status')}))
    return output, result


def test_fresh_runs_trace_actual_next_context(student):
    cli('checkpoint', 'rejoin', '03-memory', '--exercises', student)
    runs = [run(student, 'b-compare') for _ in range(2)]
    assert runs[0][1]['run_id'] != runs[1][1]['run_id']
    workspaces = set()
    for output, result in runs:
        assert result['quality_pass'] and result['status'] == 'completed'
        config = load(output / 'config.json')
        workspaces.add(config['workspace']['workspace_id'])
        assert config['evidence_kind'] == 'synthetic'
        requests = journal(output / 'requests.jsonl')
        traces = journal(output / 'memory-context.jsonl')
        assert len(traces) == len(requests) == 7
        states = []
        for line, (trace, request) in enumerate(zip(traces, requests), 1):
            context = request['body']['input']
            snapshots = [json.loads(part['text'][len(PREFIX):]) for item in context for part in item.get('content', [])
                         if isinstance(part, dict) and part.get('text', '').startswith(PREFIX)]
            assert trace['context_path'] == 'requests.jsonl' and trace['context_line'] == line
            assert trace['attempt_id'] == request['attempt_id'] and trace['memory'] == snapshots
            assert trace['context_bytes'] == len(json.dumps(context, ensure_ascii=False, separators=(',', ':')).encode())
            assert len(snapshots) == 1
            state = snapshots[0]
            assert len(json.dumps(state, ensure_ascii=False, separators=(',', ':')).encode()) <= state['limits']['bytes']
            states.append(state)
        assert states[0]['ledger'] == [] and states[0]['unresolved'] == []
        final = states[-1]
        assert final['omitted_entries'] == 0
        cited = {span['source_id'] for claim in load(output / 'claims.json')['claims'] for span in claim['evidence']}
        assert cited <= {entry['passage_id'].split(':')[0] for entry in final['ledger']}
        assert final['sources']['EV-S05']['conflict_status'] == 'superseded'
        assert final['sources']['EV-S06']['date'] == '2026-10-12'
        assert '60 seconds' in by_source(final, 'EV-S01')[-1]['claim']
        assert 'shared charger' in by_source(final, 'EV-S01')[0]['claim']
        assert len([g for g in final['experiments'] if g['experiment_id'] in ('EV-E-Q1', 'EV-E-Q2')]) == 2
        # After compaction an early read is in memory, no longer a raw result.
        raw_results = [item['output'] for item in requests[-1]['body']['input'] if item.get('type') == 'function_call_output']
        assert raw_results == []
        assert 'EV-S06' in [q['source_id'] for q in states[3]['unresolved']]
        assert 'EV-S06' not in [q['source_id'] for q in states[4]['unresolved']]
        for admission in journal(output / 'reservations.jsonl'):
            assert admission['admitted']
            assert admission['reserved_tokens'] + admission['observed_tokens_before'] <= config['budgets']['total_tokens']
    assert len(workspaces) == 2


def saved(student, name):
    path = student / 'runs/versions' / name
    cli('snapshot', '--exercises', student, '--name', name, '--output', path)
    return path


def test_memory_keeps_search_discovery_actionable(student):
    cli('checkpoint', 'rejoin', '03-memory', '--exercises', student)
    snapshot = saved(student, 'search-with-memory')
    cache = student / 'runs/cache'
    cli('run', 'prepare', '--cache', cache, '--export', FIXED / 'runtime/fixtures/rating-support.zip')
    script = student / 'provider.json'
    script.write_text(json.dumps([response(1, 'read', dict(source_id='EV-S01')),
                                 response(2, 'search', dict(query='Queue Repair', limit=8)),
                                 response(3, 'read', dict(source_id='EV-S03')), response(4)]))
    cli('run', 'run', '--snapshot', snapshot, '--exercises', student, '--cache', cache,
        '--script', script, '--tools', 'read,search', '--name', 'discovery')
    requests = journal(student / 'runs/discovery/requests.jsonl')
    assert len(requests) == 4
    search_outputs = [json.loads(item['output']) for item in requests[2]['body']['input'] if item.get('type') == 'function_call_output']
    assert search_outputs[0]['tool'] == 'search' and 'EV-S03' in json.dumps(search_outputs)
    final_memory = [json.loads(part['text'][len(PREFIX):]) for item in requests[-1]['body']['input'] for part in item.get('content', [])
                    if isinstance(part, dict) and part.get('text', '').startswith(PREFIX)][0]
    assert by_source(final_memory, 'EV-S01') and by_source(final_memory, 'EV-S03')


def test_offline_ab_comparison_preserves_a_and_surfaces_regression(student):
    # Earlier search capability remains runnable with the same public scripts.
    cli('checkpoint', 'rejoin', '02-search', '--exercises', student)
    baseline = saved(student, 'before-memory')
    backup = cli('checkpoint', 'rejoin', '03-memory', '--exercises', student)
    assert (Path(backup['backup']) / 'harness/main.ts').read_bytes() == (baseline / 'harness/main.ts').read_bytes()
    candidate = saved(student, 'with-memory')
    assert (baseline / 'prompts/system.md').read_bytes() == (candidate / 'prompts/system.md').read_bytes()
    output, result = run(student, 'a-find')
    assert result['quality_pass']
    comparison = cli('checkpoint', 'compare', '--baseline', baseline, '--candidate', candidate, '--output', student / 'runs/ab')
    print(json.dumps(comparison))
    assert comparison['before']['A']['successes'] == comparison['after']['A']['successes'] == 1
    assert comparison['before']['B']['successes'] == 0 and comparison['after']['B']['successes'] == 1
    assert comparison['recommendation']['choice'] == 'retain'
    details = load(student / 'runs/ab/comparison.json')
    for role in ('baseline', 'candidate'):
        print(json.dumps({role: [dict(run_id=a['run_id'], stop_reason=a['score']['stop_reason'],
            model_attempts=a['score']['model_attempts'], total_tokens=a['score']['total_tokens']) for a in details['attempts'][role]]}))
    # A deliberately broken student edit must be graded, not hidden by B success.
    main = student / 'harness/main.ts'
    main.write_text(main.read_text().replace('return JSON.parse(text);', 'const output = JSON.parse(text); output.claims = []; return output;'))
    regressed = saved(student, 'regressed')
    regression = cli('checkpoint', 'compare', '--baseline', candidate, '--candidate', regressed, '--output', student / 'runs/regression')
    print(json.dumps(regression))
    assert regression['before']['A']['successes'] == 1 and regression['after']['A']['successes'] == 0
    assert regression['recommendation']['choice'] == 'revert'
    # Saved earlier directories survive further rejoining/editing.
    assert load(baseline / 'snapshot.json')['snapshot_id'] == 'before-memory'
