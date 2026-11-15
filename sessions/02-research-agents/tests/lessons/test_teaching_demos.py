"""Execute the teaching helper and public offline fallbacks; no provider calls."""

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

SESSION = Path(__file__).resolve().parents[2]
FIXTURES = SESSION / 'cursus/fixtures/research-loop'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def journal(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def command(*args):
    env = {k: v for k, v in os.environ.items() if not k.endswith('API_KEY')}
    result = subprocess.run([sys.executable, *map(str, args)], cwd=SESSION, env=env,
                            capture_output=True, text=True, timeout=180)
    print(result.stdout, result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def cli(module, *args):
    return json.loads(command('-m', 'exercises.fixed.' + module, *args))


@pytest.fixture(scope='module', autouse=True)
def runtime():
    result = subprocess.run(['node', '--version'], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == 'v24.15.0', 'use mise exec node@24.15.0 -- uv run --locked pytest ...'
    assert read(SESSION / 'node_modules/@earendil-works/pi-agent-core/package.json')['version'] == '1.5.2', 'install locked session dependencies first'


def test_prepare_and_public_replay_fallbacks():
    with TemporaryDirectory(prefix='s2-teaching-test-') as temporary:
        root = Path(temporary) / 'path with spaces'
        command('-m', 'cursus.demos.research_loop', 'prepare', '--output', root)
        manifest = read(root / 'manifest.json')
        for entry in manifest['demos']:
            name = entry['name']
            generated = root / name
            score = read(generated / 'scorecard.json')
            assert score['evidence_kind'] == 'synthetic'
            for label, source in [('generated', generated), ('bundled', FIXTURES / name)]:
                output = root / (label + '-replay-' + name)
                result = cli('replay', '--run', source, '--out', output)
                original = read(source / 'scorecard.json')
                assert result['evidence_kind'] == 'replay' and result['source_evidence_kind'] == 'synthetic'
                assert result['replay_of'] == original['run_id']
                for key in ('quality_pass', 'total_tokens', 'model_attempts', 'service_errors', 'stop_reason'):
                    assert result[key] == original[key]
                assert read(output / 'scorecard.json')['tool_invocations'] == original['tool_invocations']
            if name == 'a-gap':
                assert not score['quality_pass'] and score['required_facts_met'] == 0
                assert score['model_attempts'] == 1 and score['tool_invocations'] == 0
            elif name == 'b-memory':
                memory = journal(generated / 'memory-context.jsonl')[-1]['memory'][0]
                assert memory['sources']['EV-S05']['superseded_by'] == ['EV-S06']
                group = next(g for g in memory['experiments'] if g['experiment_id'] == 'EV-E-Q1')
                assert {p.split(':')[0] for p in group['passage_ids']} == {'EV-S07', 'EV-S08', 'EV-S09'}
                assert score['quality_pass']
            elif name == 'c-rows':
                tool = next(t for t in journal(generated / 'tool-results.jsonl') if t['result']['tool'] == 'check_table')
                calculation = journal(generated / 'memory-context.jsonl')[-1]['memory'][0]['calculations'][0]
                assert calculation['pairs'] == tool['result']['data']['pairs']
                assert calculation['denominator'] == sum(p['left_value'] for p in calculation['pairs'])
                assert calculation['candidate_total'] == sum(p['right_value'] for p in calculation['pairs'])
                assert calculation['reduction_percent'] == 100 * (calculation['denominator'] - calculation['candidate_total']) / calculation['denominator']
                assert any(c['kind'] == 'uncertainty' for c in read(generated / 'claims.json')['claims'])
                assert score['quality_pass']
            else:
                tools = [e for e in journal(generated / 'trace.jsonl') if e['type'] == 'tool_invocation']
                assert tools[0]['result']['status'] == 'error'
                assert tools[1]['result']['status'] == 'ok' and tools[1]['retry_of'] == tools[0]['tool_call_id']
                assert tools[0]['input']['arguments'] == tools[1]['input']['arguments']
                assert score['tool_invocations'] == len(tools) and score['service_errors'] == 1
                assert score['quality_pass'] and any(t['input']['tool'] == 'search' for t in tools[2:])


def test_edit_rejoin_and_remaining_checkpoint_commands():
    with TemporaryDirectory(prefix='s2-teaching-checkpoints-') as temporary:
        workspace = Path(temporary) / 'exercises'
        for version in ('00-model', '01-read', '02-search', '03-memory', '04-audit-stop'):
            result = cli('checkpoint', 'rejoin', version, '--exercises', workspace)
            if (Path(result['backup']) / 'harness/student.txt').exists():
                assert (Path(result['backup']) / 'harness/student.txt').read_text() == 'preserve me'
            (workspace / 'harness/student.txt').write_text('preserve me')
            if version in ('01-read', '02-search'):
                (workspace / 'harness/student.txt').unlink()
                run = cli('checkpoint', 'run', version, '--offline', '--exercises', workspace)
                events = journal(Path(run['output']) / 'trace.jsonl')
                names = [e['input']['tool'] for e in events if e['type'] == 'tool_invocation']
                assert names == (['read'] if version == '01-read' else ['read', 'search', 'read'])
        for scenario, stop in [('repeated-retrieval', 'no_progress'), ('missing-source', 'service_error')]:
            run = cli('checkpoint', 'run', '04-audit-stop', '--offline', '--scenario', scenario, '--exercises', workspace)
            assert run['stop_reason'] == stop and not run['quality_pass']
            assert (Path(run['output']) / 'report.md').is_file()
