"""Quality-first comparison of saved versions. No provider calls without --live."""

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from . import run as launcher
from .runtime import bundle
from .schemas.validate import TOKEN_FIELDS, summarize_trace, validate
from .snapshot import digest, encoded, verify

FIXED = Path(__file__).resolve().parent
ROLES = ('baseline', 'candidate')
Json = dict[str, Any]


def lines(path: Path) -> list[Json]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def version(path: Path) -> Json:
    saved = verify(path)
    if (saved['schema_version'] != '1.0' or not saved['snapshot_id'] or
            not (path / 'harness/main.ts').is_file() or not saved['files']['prompts']):
        raise ValueError('missing version metadata or runnable harness/prompts')
    return saved


def schedule(mode: str, support: Path) -> list[Json]:
    # The announced schedule is a local orchestration input, separate from the
    # pinned rating bundle. Its exact bytes are retained beside shared controls.
    public = launcher.read(FIXED / 'config/public/manifest.json')
    variants = {(v['case_id'], v['variant_id']): v for v in public['variants']}
    return [dict(slot, case=variants[slot['case_id'], slot['variant_id']]['path'].removeprefix('cases/'),
                 tools=launcher.read(support / 'exercises' / variants[slot['case_id'], slot['variant_id']]['path'] / 'case.json')['registered_tools'])
            for slot in public['schedule'][mode]]


def expected_config(shared: Json, slot: Json, saved: Json) -> Json:
    options, files = shared['settings'], shared['support_files']
    policy = launcher.read(FIXED / 'config/policy.v1.json')
    policy.update(budgets=options['budgets'], rating_bundle=shared['rating_bundle'])
    connection = options['connection']
    prefix = 'exercises/cases/' + slot['case'] + '/'
    return dict(case_id=slot['case_id'], variant_id=slot['variant_id'], seed=slot['seed'], trial=slot['trial'],
                mode=shared['mode'], provider=connection['provider'], model=connection['model'],
                endpoint_alias=connection['endpoint_alias'], settings={k: connection['settings'][k] for k in ('temperature', 'sampling_seed', 'max_output_tokens')},
                budgets=options['budgets'], rating_bundle=shared['rating_bundle'], snapshot_id=saved['snapshot_id'],
                evidence_kind=shared['evidence_kind'], policy_sha256=digest(encoded(policy)),
                hashes=dict(model=digest(encoded(connection['model'])),
                            settings=digest(encoded(dict(options=options, tools=slot['tools']))),
                            corpus=digest(encoded({k: v for k, v in files.items() if k.startswith(prefix)})),
                            evaluator=digest(encoded({k: v for k, v in files.items() if '/grading/' in k or '/schemas/' in k})),
                            harness=digest(encoded(saved['files']['harness'])), prompt=digest(encoded(saved['files']['prompts'])),
                            rating_bundle=shared['rating_bundle']['sha256']))


def check_attempt(path: Path, shared: Json, slot: Json, saved: Json) -> Json:
    config = launcher.read(path / 'config.json')
    expected = expected_config(shared, slot, saved)
    if any(config.get(key) != value for key, value in expected.items()):
        raise ValueError('incompatible run metadata: ' + ', '.join(k for k in expected if config.get(k) != expected[k]))
    inputs = launcher.read(path / 'run-inputs.json')
    if inputs['settings'] != shared['settings'] or inputs['tools'] != slot['tools'] or inputs['mode'] != 'rating' or inputs['snapshot'] != saved:
        raise ValueError('incompatible saved settings/tools/version')
    if not config['workspace']['fresh']:
        raise ValueError('workspace was not fresh')
    events = lines(path / 'trace.jsonl')
    summary = summarize_trace(events, config['run_id'])
    measured = lines(path / 'effective-settings.jsonl') if (path / 'effective-settings.jsonl').exists() else []
    attempts = [e for e in events if e['type'] == 'model_attempt']
    by_id = {e['attempt_id']: e for e in measured}
    if len(by_id) != len(measured) or set(by_id) - {e['attempt_id'] for e in attempts}:
        raise ValueError('incompatible effective attempt identities')
    effective_complete = True
    for attempt in attempts:
        # A killed dispatch may have no returned adapter metadata. Preserve it as
        # incomplete evidence; never claim effective settings were verified.
        if attempt['attempt_id'] not in by_id:
            effective_complete = False
            continue
        effective = by_id[attempt['attempt_id']]
        connection = shared['settings']['connection']
        if (any(effective.get(k) != connection[k] for k in ('provider', 'endpoint_alias', 'model', 'settings')) or
                effective.get('route') != 'POST /v1/responses' or effective.get('stream') is not True or effective.get('store') is not False):
            raise ValueError('incompatible effective model settings')
    score = launcher.read(path / 'scorecard.json')
    validate('scorecard', score)
    if any(score.get(k) != config[k] for k in ('hashes', 'policy_sha256', 'evidence_kind', 'run_id', 'case_id', 'variant_id')) or any(score[k] != v for k, v in summary.items()):
        raise ValueError('incompatible scorecard metadata/accounting')
    known = {field: sum(e['usage'][field] or 0 for e in attempts) for field in TOKEN_FIELDS}
    errors = [dict(kind=e['type'], **e['error']) for e in events if e.get('error')]
    errors += [dict(kind='tool_invocation', **e['result']['error']) for e in events if e['type'] == 'tool_invocation' and e['result']['error']]
    runtime = launcher.read(path / 'runtime-status.json')
    if runtime['detail'] != 'completed':
        errors.append(dict(kind='runtime', code=runtime['detail']))
    return dict(status='complete', score=score, known_usage=known, errors=errors,
                effective_settings_status='complete' if effective_complete else 'missing',
                runtime=runtime, workspace_id=config['workspace']['workspace_id'])


def aggregate(attempts: list[Json]) -> Json:
    """Scheduled slots remain the denominator, including absent/failed artifacts."""
    scores = [a['score'] for a in attempts if a['status'] == 'complete']
    successes = sum(s['quality_pass'] and s['stop_reason'] == 'completed' for s in scores)
    complete = len(scores) == len(attempts) and all(a.get('effective_settings_status', 'complete') == 'complete' for a in attempts)
    measured = complete and all(s['usage']['status'] == 'complete' for s in scores)
    usage = {f: sum(s['usage'][f] for s in scores) if complete and all(s['usage'][f] is not None for s in scores) else None for f in TOKEN_FIELDS}
    known = {f: sum(a['known_usage'][f] for a in attempts if a['status'] == 'complete') for f in TOKEN_FIELDS}
    # Input/output can be completely observed even when cache detail is absent.
    # Preserve that total while withholding any efficiency conclusion.
    total = sum(s['total_tokens'] for s in scores) if len(scores) == len(attempts) and all(s['total_tokens'] is not None for s in scores) else None
    per_case = {}
    for case in sorted({a['slot']['case_id'] for a in attempts}):
        selected = [a for a in attempts if a['slot']['case_id'] == case]
        passed = sum(a['status'] == 'complete' and a['score']['quality_pass'] and a['score']['stop_reason'] == 'completed' for a in selected)
        per_case[case] = dict(scheduled=len(selected), successes=passed, pass_rate=passed / len(selected))
    checks: dict[str, Counter] = {}
    failures: Counter = Counter()
    for score in scores:
        for check in score['grading_assertions']:
            count = checks.setdefault(check['category'], Counter())
            count['total'] += 1
            count['passed'] += check['passed']
            if not check['passed']:
                failures[check['assertion_id']] += 1
    required_total = sum(s['required_facts_total'] for s in scores)
    return dict(scheduled=len(attempts), recorded=len(scores), missing_or_invalid=len(attempts) - len(scores),
                status='complete' if complete else 'incomplete', successes=successes, pass_rate=successes / len(attempts),
                per_case=per_case, quality_gates_pass=complete and successes == len(attempts),
                assertions=checks, requirement_failures=failures,
                required_facts_met=sum(s['required_facts_met'] for s in scores), required_facts_total=required_total,
                fact_coverage=sum(s['required_facts_met'] for s in scores) / required_total if required_total else None,
                **{k: sum(s[k] for s in scores) for k in ('model_attempts', 'logical_requests', 'tool_invocations', 'service_errors', 'elapsed_ms')},
                usage=dict(usage, status='complete' if measured else 'incomplete'), known_usage_subtotals=known,
                total_tokens=total, tokens_per_success=total / successes if measured and successes else None,
                efficiency_status='zero_success' if not successes else 'available' if measured else 'incomplete_usage',
                stop_reasons=dict(Counter(s['stop_reason'] for s in scores)),
                errors=[dict(attempt=a['run_id'], **e) for a in attempts for e in a.get('errors', [])],
                evidence_kinds=sorted({s['evidence_kind'] for s in scores}), peer_review='pending')


def recommend(before: Json, after: Json) -> Json:
    if before['status'] != 'complete' or after['status'] != 'complete':
        choice, reasons = 'insufficient_evidence', ['Missing or incompatible scheduled attempts; repair evidence and rerun.']
    else:
        regressions = [c for c, b in before['per_case'].items() if after['per_case'][c]['pass_rate'] < b['pass_rate']]
        if regressions:
            choice, reasons = 'revert', ['Per-case quality regressed: ' + ', '.join(regressions) + '. Token savings cannot offset this loss.']
        elif not after['successes']:
            choice, reasons = 'revert', ['Zero successful candidate attempts; tokens per success is undefined.']
        elif any(after['per_case'][c]['pass_rate'] > b['pass_rate'] for c, b in before['per_case'].items()):
            choice, reasons = 'retain', ['Requirement fix: a per-case pass rate improved without decreasing any other; no efficiency comparison.']
        elif not after['quality_gates_pass']:
            choice, reasons = 'revert', ['Candidate still fails required quality gates; no efficiency comparison.']
        elif before['efficiency_status'] != 'available' or after['efficiency_status'] != 'available':
            choice, reasons = 'insufficient_evidence', ['Quality passes, but measured usage/cache accounting is incomplete; efficiency is unknown.']
        elif after['tokens_per_success'] < before['tokens_per_success']:
            choice, reasons = 'retain', ['Quality preserved with fewer measured total tokens per successful attempt.']
        else:
            choice, reasons = 'revert', ['Quality preserved, but no measured token-per-success reduction.']
    return dict(choice=choice, reasons=reasons, status='provisional', peer_review='pending',
                elapsed_time_ranked=False, machine_gates='pass' if choice == 'retain' else 'fail')


def collect(output: Path) -> Json:
    shared = launcher.read(output / 'shared.json')
    pin, files = bundle.verify(output / 'cache')
    if shared['support_files'] != files or shared['rating_bundle'] != {k: pin[k] for k in ('revision', 'sha256', 'illustrative')}:
        raise ValueError('incompatible comparison rating support')
    versions = {role: version(output / 'versions' / role) for role in ROLES}
    records: dict[str, list[Json]] = {role: [] for role in ROLES}
    workspaces = set()
    for role in ROLES:
        for index, slot in enumerate(shared['schedule']):
            run_id = f'{role}-{index + 1:02d}'
            path = output / 'runs' / run_id
            try:
                if (path / 'shared.json').read_bytes() != (output / 'shared.json').read_bytes():
                    raise ValueError('incompatible shared schedule/configuration bytes')
                data = check_attempt(path, shared, slot, versions[role])
                if data['workspace_id'] in workspaces:
                    raise ValueError('workspace reused')
                workspaces.add(data['workspace_id'])
            except (OSError, ValueError, KeyError, TypeError) as error:
                data = dict(status='missing' if isinstance(error, OSError) else 'incompatible', errors=[dict(kind='comparison', code=str(error))])
            records[role].append(dict(run_id=run_id, slot=slot, **data))
    before, after = (aggregate(records[role]) for role in ROLES)
    decision = recommend(before, after)
    invalid = any(a['status'] == 'incompatible' for attempts in records.values() for a in attempts)
    result = dict(schema_version='1.0', mode=shared['mode'], evidence_kind=shared['evidence_kind'],
                  evidence_status='synthetic' if shared['evidence_kind'] == 'synthetic' else 'captured_live_pending_peer_review',
                  peer_review=dict(status='pending', role='Human prose support audit; separate from machine gates.',
                                   checklists=[f'runs/{a["run_id"]}/peer-review.md' for attempts in records.values() for a in attempts]),
                  before=before, after=after, recommendation=decision, attempts=records,
                  exit_code=2 if invalid else 0 if decision['machine_gates'] == 'pass' else 1)
    write_scorecards(output, result)
    return result


def write_scorecards(output: Path, result: Json) -> None:
    launcher.write(output / 'comparison.json', result)
    for role, key in [('baseline', 'before'), ('candidate', 'after')]:
        score = result[key]
        launcher.write(output / f'{key}.json', score)
        text = [f'# {role.title()} scorecard', '', f'Status: {score["status"]}; peer prose review: pending.', '',
                '| Case | Successful / scheduled | Pass rate |', '| --- | --- | --- |']
        text += [f'| {case} | {s["successes"]} / {s["scheduled"]} | {s["pass_rate"]:.3f} |' for case, s in score['per_case'].items()]
        text += ['', 'All-attempt measurements (including failures and retries):', '', '```json', json.dumps(score, indent=2), '```', '']
        (output / f'{key}.md').write_text('\n'.join(text), encoding='utf-8')
    decision = result['recommendation']
    text = ['# Saved-version comparison', '', f'Evidence: {result["evidence_status"]}. Mode: {result["mode"]}.', '',
            f'Machine recommendation: **{decision["choice"]}** ({decision["status"]}); gates: {decision["machine_gates"]}.', '']
    text += ['- ' + reason for reason in decision['reasons']]
    text += ['', '[Before](before.md) · [After](after.md) · [All scheduled attempts](comparison.json) · [Shared controls](shared.json)', '',
             'Peer prose review: **pending**. Inspect each attempt’s peer-review.md beside its report and evidence. Machine results do not establish prose support.', '',
             'Elapsed time is diagnostic only and never determines retention. Synthetic results do not verify live compatibility, autonomy or classroom readiness.', '']
    (output / 'comparison.md').write_text('\n'.join(text), encoding='utf-8')


def compare(experiment: Path, output: Path, live: bool = False) -> Json:
    experiment, output = experiment.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    spec = launcher.read(experiment)
    if set(spec) - {'schema_version', 'experiment_type', 'mode', 'settings', 'baseline', 'candidate', 'rating_export', 'scripts'}:
        raise ValueError('unsupported experiment fields; configure shared controls once')
    if spec['schema_version'] != '1.0' or spec['experiment_type'] not in ('harness', 'prompt') or spec['mode'] not in ('class', 'submission'):
        raise ValueError('invalid experiment type/mode/version')
    scripted = 'scripts' in spec
    if scripted == live:
        raise ValueError('choose scripted experiment or explicit --live for a live experiment')
    base = experiment.parent
    saved = {role: version((base / spec[role]).resolve()) for role in ROLES}
    frozen_group = 'prompts' if spec['experiment_type'] == 'harness' else 'harness'
    if saved['baseline']['files'][frozen_group] != saved['candidate']['files'][frozen_group]:
        raise ValueError('incompatible versions: experiment changes the frozen ' + frozen_group)
    options = launcher.settings(base / spec['settings'])
    cache = output / 'cache'
    bundle.prepare(cache, base / spec['rating_export'] if spec.get('rating_export') else None)
    pin, files = bundle.verify(cache)
    shared: Json = dict(schema_version='1.0', mode=spec['mode'], experiment_type=spec['experiment_type'],
                  evidence_kind='synthetic' if scripted else 'captured_live', settings=options,
                  rating_bundle={k: pin[k] for k in ('revision', 'sha256', 'illustrative')}, support_files=files,
                  schedule=schedule(spec['mode'], cache))
    launcher.write(output / 'experiment.json', spec)
    launcher.write(output / 'shared.json', shared)
    launcher.write(output / 'settings.json', options)
    shutil.copyfile(FIXED / 'config/public/manifest.json', output / 'public-manifest.json')
    scripts = {}
    if scripted:
        (output / 'scripts').mkdir()
        for slot in shared['schedule']:
            case = slot['case_id']
            source = base / spec['scripts'][case]
            scripts[case] = output / 'scripts' / f'{case}.json'
            shutil.copyfile(source, scripts[case])
            launcher.read(scripts[case])  # reject malformed fixtures before launching
    for role in ROLES:
        shutil.copytree(base / spec[role], output / 'versions' / role)
    for role in ROLES:
        for index, slot in enumerate(shared['schedule']):
            run_id = f'{role}-{index + 1:02d}'
            path = output / 'runs' / run_id
            try:
                launcher.run(argparse.Namespace(snapshot=output / 'versions' / role, settings=output / 'settings.json',
                    mode='rating', cache=cache, case=slot['case'], tools=','.join(slot['tools']),
                    exercises=output, name=run_id, trial=slot['trial'], seed=slot['seed'], script=scripts.get(slot['case_id'])))
                # The single-attempt launcher defaults to class. Mode records the
                # comparison schedule, not provider sampling; no task input changes.
                config = launcher.read(path / 'config.json')
                config['mode'] = shared['mode']
                launcher.write(path / 'config.json', config)
            except (OSError, ValueError, KeyError, TypeError):
                path.mkdir(parents=True, exist_ok=True)
                launcher.write(path / 'launch-error.json', dict(status='failed', code='launch_or_grading_failure'))
            launcher.write(path / 'shared.json', shared)
    return collect(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('compare')
    start.add_argument('--experiment', type=Path, required=True, help='paths in this JSON resolve relative to its directory')
    start.add_argument('--output', type=Path, required=True, help='new comparison directory; never overwritten')
    start.add_argument('--live', action='store_true', help='explicitly authorize paid calls for an experiment without scripts')
    audit = commands.add_parser('summarize', help='recheck saved metadata and rebuild scorecards, retaining scheduled denominators')
    audit.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = compare(args.experiment, args.output, args.live) if args.command == 'compare' else collect(args.output.resolve())
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps(dict(status='invalid_input', exit_code=2,
                              error='Invalid/missing version, configuration, bundle or output; inspect inputs and use a new output directory.')))
        return 2
    print(json.dumps({k: result[k] for k in ('evidence_status', 'peer_review', 'recommendation', 'exit_code')}))
    return result['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
