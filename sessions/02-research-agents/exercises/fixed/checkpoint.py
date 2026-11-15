"""Rejoin a public checkpoint, run it, or compare saved A/B versions offline."""

import argparse
import json
import shutil
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from . import evaluate
from . import run as launcher
from .snapshot import EXERCISES, inventory, save, verify

CHECKPOINTS = Path(__file__).resolve().parent / 'checkpoints'
NAMES = ('00-model', '01-read', '02-search', '03-memory')
TOOLS = ('', 'read', 'read,search', 'read,search')
GROUPS = ('harness', 'prompts')
CASES = ('a-find', 'b-compare')
MEMORY_PREFIX = 'Claim–passage memory\n'


def publish_memory_trace(output: Path) -> None:
    """Index actual outbound payloads, not a second imagined context history."""
    requests = output / 'requests.jsonl'
    rows = []
    for line, raw in enumerate(requests.read_text(encoding='utf-8').splitlines() if requests.exists() else [], 1):
        request = json.loads(raw)
        context = request['body']['input']
        snapshots = [json.loads(part['text'][len(MEMORY_PREFIX):])
                     for message in context for part in message.get('content', [])
                     if isinstance(part, dict) and part.get('text', '').startswith(MEMORY_PREFIX)]
        rows.append(dict(attempt_id=request['attempt_id'], context_path='requests.jsonl', context_line=line,
                         context_bytes=len(json.dumps(context, ensure_ascii=False, separators=(',', ':')).encode('utf-8')),
                         memory=snapshots))
    (output / 'memory-context.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')


def script_for(case: str) -> Path:
    return CHECKPOINTS / '03-memory' / ('transport-a.json' if case == 'a-find' else 'transport-b.json')


def rejoin(name: str, exercises: Path) -> dict[str, str]:
    source = CHECKPOINTS / name
    # Validate and stage both complete replacements before touching student work.
    exercises.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='s2-rejoin-') as temporary:
        staging = Path(temporary)
        for group in GROUPS:
            inventory(source / group)
            shutil.copytree(source / group, staging / group)
        backups = exercises / 'runs/backups'
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / (name + '-' + uuid.uuid4().hex)
        backup.mkdir()
        for group in GROUPS:
            current = exercises / group
            if current.exists():
                inventory(current)
                shutil.copytree(current, backup / group)
        # Both editable directories have been preserved before either is replaced.
        for group in GROUPS:
            current = exercises / group
            if current.exists():
                shutil.rmtree(current)
            shutil.copytree(staging / group, current)
    return dict(checkpoint=name, backup=str(backup.resolve()), entry_point='harness/main.ts')


def execute(args: argparse.Namespace) -> dict:
    exercises = args.exercises.resolve()
    name = args.name or ('live-' if args.live else 'synthetic-') + args.checkpoint + '-' + uuid.uuid4().hex[:8]
    snapshot = args.snapshot or exercises / 'runs/versions' / name
    if args.snapshot:
        verify(snapshot)
    else:
        save(exercises, snapshot, name)
    cache = exercises / 'runs/cache/rating-v1'
    launcher.bundle.prepare(cache, launcher.FIXED / 'runtime/fixtures/rating-support.zip')
    result = launcher.run(argparse.Namespace(
        snapshot=snapshot, settings=args.settings, mode='rating', cache=cache,
        case=args.case, tools=TOOLS[NAMES.index(args.checkpoint)], name=name,
        trial=1, seed=20261115, exercises=exercises,
        script=None if args.live else script_for(args.case) if args.checkpoint == '03-memory' else CHECKPOINTS / args.checkpoint / 'transport.json',
    ))
    output = exercises / 'runs' / name
    score = launcher.read(output / 'scorecard.json')
    comparison = dict(evidence_kind=score['evidence_kind'],
                      reference=str(cache / 'exercises/cases' / args.case / 'reference.json'),
                      required_facts_met=score['required_facts_met'],
                      required_facts_total=score['required_facts_total'],
                      failed_assertion_ids=score['failed_assertion_ids'],
                      peer_review='pending: compare report.md with reference and inspect trace.jsonl')
    launcher.write(output / 'checkpoint-comparison.json', comparison)
    publish_memory_trace(output)
    return dict(result, output=str(output), snapshot=str(snapshot), comparison=comparison)


def compare(args: argparse.Namespace) -> dict:
    """Thin A/B class smoke; the general evaluator owns submission schedules."""
    saved = {role: verify(getattr(args, role)) for role in evaluate.ROLES}
    if saved['baseline']['files']['prompts'] != saved['candidate']['files']['prompts']:
        raise ValueError('memory comparison must hold prompts fixed')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    launcher.write(output / 'settings.json', launcher.settings(args.settings))
    cache = output / 'cache'
    launcher.bundle.prepare(cache, launcher.FIXED / 'runtime/fixtures/rating-support.zip')
    pin, files = launcher.bundle.verify(cache)
    schedule = [dict(case=case, case_id=case[0].upper(), variant_id='base', seed=20261115,
                     trial=1, tools=['read', 'search']) for case in CASES]
    shared = dict(mode='class', evidence_kind='synthetic', settings=launcher.settings(output / 'settings.json'),
                  rating_bundle={k: pin[k] for k in ('revision', 'sha256', 'illustrative')},
                  support_files=files, schedule=schedule)
    launcher.write(output / 'shared.json', shared)
    (output / 'scripts').mkdir()
    for case in CASES:
        shutil.copyfile(script_for(case), output / 'scripts' / (case[0].upper() + '.json'))
    records: dict[str, list[dict]] = {role: [] for role in evaluate.ROLES}
    for role in evaluate.ROLES:
        snapshot = output / 'versions' / role
        shutil.copytree(getattr(args, role), snapshot)
        for slot, case in zip(schedule, CASES):
            case_id = case[0].upper()
            name = role + '-' + case_id
            launcher.run(argparse.Namespace(snapshot=snapshot, settings=output / 'settings.json', mode='rating',
                cache=cache, case=case, tools='read,search', name=name, trial=1, seed=slot['seed'],
                exercises=output, script=output / 'scripts' / (case_id + '.json')))
            run_output = output / 'runs' / name
            publish_memory_trace(run_output)
            records[role].append(dict(run_id=name, slot=slot,
                **evaluate.check_attempt(run_output, shared, slot, saved[role])))
    before, after = (evaluate.aggregate(records[role]) for role in evaluate.ROLES)
    result = dict(mode='class', evidence_kind='synthetic', evidence_status='synthetic',
                  before=before, after=after, recommendation=evaluate.recommend(before, after), attempts=records)
    evaluate.write_scorecards(output, result)
    return dict(output=str(output), before=before['per_case'], after=after['per_case'], recommendation=result['recommendation'])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('rejoin', 'run'):
        sub = commands.add_parser(command)
        sub.add_argument('checkpoint', choices=NAMES)
        sub.add_argument('--exercises', type=Path, default=EXERCISES)
        if command == 'run':
            mode = sub.add_mutually_exclusive_group()
            mode.add_argument('--offline', action='store_true', help='synthetic scripted responses; default')
            mode.add_argument('--live', action='store_true', help='explicit paid API opt-in; environment credentials')
            sub.add_argument('--name', help='new run/snapshot identifier; defaults to a unique name')
            sub.add_argument('--settings', type=Path, default=launcher.FIXED / 'config/run.v1.json')
            sub.add_argument('--case', choices=CASES, default='a-find')
            sub.add_argument('--snapshot', type=Path, help='run a saved version instead of saving current edits')
    comparison = commands.add_parser('compare', help='synthetic A/B comparison, identical prompt/settings/scripts')
    comparison.add_argument('--baseline', type=Path, required=True)
    comparison.add_argument('--candidate', type=Path, required=True)
    comparison.add_argument('--output', type=Path, required=True)
    comparison.add_argument('--settings', type=Path, default=launcher.FIXED / 'config/run.v1.json')
    args = parser.parse_args()
    try:
        result = compare(args) if args.command == 'compare' else rejoin(args.checkpoint, args.exercises) if args.command == 'rejoin' else execute(args)
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(2, 'checkpoint failed: check inputs, choose a new run name; any backup/partial run is retained\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
