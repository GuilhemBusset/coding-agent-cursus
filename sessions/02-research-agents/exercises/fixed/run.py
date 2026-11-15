"""Fresh research runs: prepare, run, and post-run grade. No paid calls by default."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .runtime import bundle
from .snapshot import EXERCISES, digest, encoded, inventory, verify

FIXED = Path(__file__).resolve().parent
SESSION = FIXED.parents[1]
# Operational fields only. No arbitrary agent, provider, Python or Node options.
ENV_FIELDS = {'PATH', 'Path', 'SYSTEMROOT', 'SystemRoot', 'WINDIR', 'COMSPEC', 'PATHEXT',
              'TMPDIR', 'TMP', 'TEMP', 'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'SSL_CERT_DIR'}


def environment(credentials: bool = False) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in ENV_FIELDS}
    if credentials:
        env.update({k: v for k, v in os.environ.items() if k in {'OPENAI_API_KEY', 'COURSE_API_KEY'} or k.startswith('COURSE_ENDPOINT_')})
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def write(path: Path, value: Any) -> None:
    path.write_bytes(encoded(value))


def settings(path: Path) -> dict[str, Any]:
    value = read(path)
    if set(value) != {'connection', 'budgets', 'tool_timeout_ms', 'run_timeout_ms'}:
        raise ValueError('unsupported run settings')
    connection = value['connection']
    if set(connection) != {'provider', 'endpoint_alias', 'model', 'settings', 'timeout_ms', 'retries'}:
        raise ValueError('unsupported connection settings; credentials are environment-only')
    if connection['provider'] not in ('openai', 'openai-compatible'):
        raise ValueError('unsupported provider')
    if not isinstance(connection['endpoint_alias'], str) or not re.fullmatch('[a-z][a-z0-9_-]{0,40}', connection['endpoint_alias']):
        raise ValueError('endpoint must be an alias')
    if not isinstance(connection['model'], str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', connection['model']) or connection['model'].startswith('sk-'):
        raise ValueError('invalid model identifier')
    model_settings = connection['settings']
    if set(model_settings) != {'temperature', 'sampling_seed', 'max_output_tokens', 'reasoning'} or model_settings['temperature'] is not None or model_settings['sampling_seed'] is not None or model_settings['reasoning'] != 'none':
        raise ValueError('unsupported model settings')
    for container, field, low, high in [(connection, 'timeout_ms', 1, 120000), (connection, 'retries', 0, 2),
                                        (model_settings, 'max_output_tokens', 16, 8192)]:
        if type(container[field]) is not int or not low <= container[field] <= high:
            raise ValueError('connection limits outside supported bounds')
    budgets = value['budgets']
    if set(budgets) != {'model_attempts', 'tool_invocations', 'total_tokens'} or any(type(n) is not int or n < 1 for n in budgets.values()):
        raise ValueError('budgets must be positive integers')
    for field in ('tool_timeout_ms', 'run_timeout_ms'):
        if type(value[field]) is not int or not 1 <= value[field] <= 1800000:
            raise ValueError('timeouts must be 1..1800000 ms')
    return value


def recover(output: Path, config: dict[str, Any], detail: str, elapsed_ms: int) -> None:
    """Retain and reconcile in-flight dispatches if the worker is killed/stalls."""
    trace = output / 'trace.jsonl'
    events = [json.loads(s) for s in trace.read_text(encoding='utf-8').splitlines()] if trace.exists() else []
    events = [e for e in events if e['type'] != 'run_end']
    dispatched = output / 'dispatches.jsonl'
    dispatches = [json.loads(s) for s in dispatched.read_text(encoding='utf-8').splitlines()] if dispatched.exists() else []
    known = {e.get('attempt_id') for e in events if e['type'] == 'model_attempt'}
    known_tools = {e.get('tool_call_id') for e in events if e['type'] == 'tool_invocation'}
    elapsed = max([e['elapsed_ms'] for e in events] + [d['elapsed_ms'] for d in dispatches] + [elapsed_ms])
    for dispatch in dispatches:
        if dispatch['type'] == 'model' and dispatch['attempt_id'] not in known:
            events.append(dict(type='model_attempt', request_id=dispatch['request_id'], attempt_id=dispatch['attempt_id'],
                               retry_of=dispatch['retry_of'], status='cancelled', duration_ms=max(0, elapsed - dispatch['elapsed_ms']),
                               usage=dict(status='unknown', **{k: None for k in ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens')}),
                               error=dict(code='cancelled', retryable=False), elapsed_ms=elapsed))
        elif dispatch['type'] == 'tool' and dispatch['tool_call_id'] not in known_tools:
            result = {k: dispatch['input'][k] for k in ('schema_version', 'run_id', 'tool_call_id', 'tool')}
            result.update(status='error', data=None, error=dict(code='cancelled', retryable=False))
            events.append(dict(type='tool_invocation', **{k: dispatch[k] for k in ('request_id', 'attempt_id', 'retry_of', 'tool_call_id')},
                               duration_ms=max(0, elapsed - dispatch['elapsed_ms']), input=dispatch['input'], result=result, elapsed_ms=elapsed))
    intervened = any(e['type'] == 'intervention' for e in events)
    events.append(dict(type='run_end', stop_reason='service_error', intervention=intervened, elapsed_ms=elapsed))
    for index, event in enumerate(events):
        event.update(schema_version='1.0', run_id=config['run_id'], event_id=f'event-{index}', sequence=index)
    trace.write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
    write(output / 'runtime-status.json', dict(status='stopped', stop_reason='service_error', detail=detail,
                                             elapsed_ms=elapsed, intervention=intervened))


FINALIZE = '''
import json, sys
from pathlib import Path
from exercises.fixed.schemas.validate import validate, summarize_trace
from exercises.fixed.grading.engine import grade_run
output, case = map(Path, sys.argv[1:])
config = json.loads((output / 'config.json').read_text(encoding='utf-8'))
validate('run-config', config)
events = [json.loads(s) for s in (output / 'trace.jsonl').read_text(encoding='utf-8').splitlines()]
summary = summarize_trace(events, config['run_id'])
(output / 'accounting.json').write_text(json.dumps(summary, indent=2)+'\\n', encoding='utf-8')
score = grade_run(output, case, output / 'policy.json')
if not score['output_valid'] and events[-1]['stop_reason'] == 'completed':
    events[-1]['stop_reason'] = 'invalid_output'
    (output / 'trace.jsonl').write_text(''.join(json.dumps(e)+'\\n' for e in events), encoding='utf-8')
    status = json.loads((output / 'runtime-status.json').read_text(encoding='utf-8'))
    status.update(status='stopped', stop_reason='invalid_output', detail='invalid_output')
    (output / 'runtime-status.json').write_text(json.dumps(status, indent=2)+'\\n', encoding='utf-8')
    summary = summarize_trace(events, config['run_id'])
    (output / 'accounting.json').write_text(json.dumps(summary, indent=2)+'\\n', encoding='utf-8')
    score = grade_run(output, case, output / 'policy.json')
print(json.dumps(dict(quality_pass=score['quality_pass'], model_attempts=score['model_attempts'], total_tokens=score['total_tokens'])))
'''


def grade(output: Path, support: Path, case: Path) -> dict[str, Any]:
    inputs = read(output / 'run-inputs.json')
    files = bundle.verify(support)[1] if inputs['mode'] == 'rating' else inputs['support_files']
    # A cache may contain unrelated files. Only manifest members may participate
    # in imports or grading, just as only members enter the research workspace.
    with TemporaryDirectory(prefix='s2-grade-') as temporary:
        staged = Path(temporary)
        copy_support(support, staged, files)
        # Public evidence links point to the persistent verified cache, not the
        # temporary Python import tree that is removed after evaluation.
        result = subprocess.run([sys.executable, '-c', FINALIZE, str(output), str(case)], cwd=staged,
                                env=environment(), capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError('artifact validation/grading failed; partial artifacts retained')
    return json.loads(result.stdout)


def copy_support(source: Path, destination: Path, files: dict[str, str]) -> None:
    for name, sha in files.items():
        data = (source / name).read_bytes()
        if digest(data) != sha:
            raise ValueError(f'rating bundle digest mismatch: {name}')
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def run(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = args.snapshot.resolve()
    saved = verify(snapshot)
    options = settings(args.settings)
    if args.mode == 'rating':
        pin, files = bundle.verify(args.cache)
        support = args.cache.resolve()
    else:
        support = args.exercises.resolve().parent
        files = {name: digest((support / name).read_bytes()) for name in bundle.manifest()[1]}
        pin = dict(revision='development-working-tree', sha256=digest(encoded(files)), illustrative=True)
    case_relative = Path('exercises/cases') / args.case
    # Case selection is a relative public bundle path, including optional variants.
    if case_relative.is_absolute() or '..' in case_relative.parts:
        raise ValueError('case must be a relative bundle path')
    case = read(support / case_relative / 'case.json')
    selected = args.tools.split(',') if args.tools else case['registered_tools']
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(case['registered_tools']):
        raise ValueError('tools must be selected from the case registry')
    prompts = {name: (snapshot / 'prompts' / name).read_text(encoding='utf-8') for name in saved['files']['prompts'] if name != '.gitkeep'}
    if not (snapshot / 'harness/main.ts').is_file():
        raise ValueError('snapshot needs harness/main.ts exporting run(api)')
    run_id = args.name or 'run-' + uuid.uuid4().hex
    if not run_id[0].isalnum() or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-' for c in run_id):
        raise ValueError('run name must be an identifier')
    output = args.exercises.resolve() / 'runs' / run_id
    output.mkdir(parents=True, exist_ok=False)
    policy = read(FIXED / 'config/policy.v1.json')
    identity = {k: pin[k] for k in ('revision', 'sha256', 'illustrative')}
    policy.update(budgets=options['budgets'], rating_bundle=identity)
    write(output / 'policy.json', policy)
    connection = options['connection']
    config = dict(schema_version='1.0', run_id=run_id, case_id=case['case_id'], variant_id=case['variant_id'],
                  trial=args.trial, seed=args.seed, mode='class', evidence_kind='synthetic' if args.script else 'captured_live',
                  replay_of=None, provider=connection['provider'], model=connection['model'], endpoint_alias=connection['endpoint_alias'],
                  settings={k: connection['settings'][k] for k in ('temperature', 'sampling_seed', 'max_output_tokens')},
                  budgets=options['budgets'], policy_sha256=digest((output / 'policy.json').read_bytes()),
                  hashes=dict(model=digest(encoded(connection['model'])), settings=digest(encoded(dict(options=options, tools=selected))),
                              corpus=digest(encoded({k: v for k, v in files.items() if k.startswith(case_relative.as_posix() + '/')})),
                              evaluator=digest(encoded({k: v for k, v in files.items() if '/grading/' in k or '/schemas/' in k})),
                              harness=digest(encoded(saved['files']['harness'])), prompt=digest(encoded(saved['files']['prompts'])), rating_bundle=pin['sha256']),
                  rating_bundle=identity, snapshot_id=saved['snapshot_id'], workspace=dict(workspace_id='workspace-' + uuid.uuid4().hex,
                  fresh=True, supplied_inputs=['question', 'context', 'prompt', 'tool_definitions', 'corpus_via_tools', 'output_contract']))
    write(output / 'config.json', config)
    write(output / 'run-inputs.json', dict(mode=args.mode, settings=options, tools=selected, bundle=pin,
                                        snapshot=saved, support_files=files))
    # Empty but valid partial output, explicitly recording that no result was produced.
    fallback = dict(claims=[dict(claim_id='unfinished', kind='uncertainty', assertion=dict(subject='run', predicate='findings', type='string', value='not-produced', unit=None),
                                support_status='unknown', evidence=[], reference_fact_ids=[], experiment_ids=[], supersedes_claim_ids=[])],
                    claim_anchors=[dict(claim_id='unfinished', anchor='claim-unfinished')],
                    markdown='<a id="claim-unfinished"></a>\nNo research result was produced.\n')
    started = time.monotonic()

    def recover_worker(detail: str) -> None:
        recover(output, config, detail, round((time.monotonic() - started) * 1000))

    try:
        with TemporaryDirectory(prefix='s2-run-') as temporary:
            workspace = Path(temporary)
            # Copy ONLY verified support inputs. No dependency on extra cache files.
            copy_support(support, workspace, files)
            for group in ('harness', 'prompts'):
                shutil.copytree(snapshot / group, workspace / group)
            write(workspace / 'package.json', {'type': 'module'})
            contract = {name: read(workspace / f'exercises/fixed/schemas/{name}.v1.schema.json') for name in ('claims', 'report', 'common')}
            spec = dict(run_id=run_id, output=str(output), workspace=str(workspace), support=str(workspace),
                        case_root=str(workspace / case_relative), python=sys.executable, settings=options, tools=selected,
                        prompts=prompts, task={k: case[k] for k in ('question', 'context')}, output_contract=contract,
                        script=str(args.script.resolve()) if args.script else None)
            write(workspace / 'launch.json', spec)
            try:
                process = subprocess.run(['node', str(FIXED / 'runtime/launch.ts'), str(workspace / 'launch.json')],
                                         cwd=workspace, env=environment(credentials=True), capture_output=True, text=True,
                                         timeout=options['run_timeout_ms'] / 1000 + 3)
                # Never retain raw provider/Node stderr; the worker emits structured diagnostics.
                if process.returncode or not (output / 'runtime-status.json').exists():
                    cancellation = output / 'cancellation.json'
                    recover_worker(read(cancellation)['detail'] if cancellation.exists() else 'worker_error')
            except subprocess.TimeoutExpired:
                recover_worker('run_timeout')
            except KeyboardInterrupt:
                recover_worker('cancelled')
    except OSError:
        recover_worker('worker_error')
    candidate = read(output / 'candidate-output.json') if (output / 'candidate-output.json').exists() else fallback
    if not isinstance(candidate, dict):
        candidate = {}  # Preserve the original, then grade a malformed result honestly.
    envelope = {k: config[k] for k in ('schema_version', 'run_id', 'case_id', 'variant_id')}
    write(output / 'claims.json', dict(envelope, claims=candidate.get('claims', [])))
    write(output / 'report.json', dict(envelope, claims_path='claims.json', report_path='report.md', claim_anchors=candidate.get('claim_anchors', [])))
    (output / 'report.md').write_text(str(candidate.get('markdown', '')), encoding='utf-8')
    result = grade(output, support, support / case_relative)
    return {'run_id': run_id, **result, **read(output / 'runtime-status.json')}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare', help='fetch the public pin, or import a verified offline export')
    prepare.add_argument('--cache', type=Path, default=EXERCISES / 'runs/cache/rating-v1')
    prepare.add_argument('--export', type=Path)
    launch = commands.add_parser('run')
    launch.add_argument('--snapshot', type=Path, required=True)
    launch.add_argument('--case', default='a-find')
    launch.add_argument('--cache', type=Path, default=EXERCISES / 'runs/cache/rating-v1')
    launch.add_argument('--mode', choices=['rating', 'development'], default='rating')
    launch.add_argument('--exercises', type=Path, default=EXERCISES)
    launch.add_argument('--settings', type=Path, default=FIXED / 'config/run.v1.json')
    launch.add_argument('--tools')
    launch.add_argument('--name')
    launch.add_argument('--trial', type=int, default=1)
    launch.add_argument('--seed', type=int, default=20261115)
    choice = launch.add_mutually_exclusive_group(required=True)
    choice.add_argument('--script', type=Path, help='offline scripted Responses transport (synthetic)')
    choice.add_argument('--live', action='store_true', help='explicitly permit paid provider requests')
    evaluate = commands.add_parser('grade')
    evaluate.add_argument('--run', type=Path, required=True)
    evaluate.add_argument('--cache', type=Path, default=EXERCISES / 'runs/cache/rating-v1')
    evaluate.add_argument('--case', default='a-find')
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            result = bundle.prepare(args.cache.resolve(), args.export.resolve() if args.export else None)
        elif args.command == 'grade':
            pin, _ = bundle.verify(args.cache)
            saved_config = read(args.run / 'config.json')
            if saved_config['rating_bundle'] != {k: pin[k] for k in ('revision', 'sha256', 'illustrative')}:
                raise ValueError('run does not match rating bundle')
            result = grade(args.run.resolve(), args.cache.resolve(), args.cache.resolve() / 'exercises/cases' / args.case)
        else:
            result = run(args)
    except (OSError, ValueError, KeyError, TypeError) as error:
        # Paths/URLs/provider exception strings can contain credentials. Emit only
        # known local bundle diagnostics, otherwise a fixed failure description.
        message = str(error)
        safe = message if message.startswith(('rating bundle ', 'rating manifest ', 'rating export ', 'snapshot digest ')) else 'invalid input or runtime failure; partial artifacts retained if launched'
        print(json.dumps(dict(error=safe)), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
