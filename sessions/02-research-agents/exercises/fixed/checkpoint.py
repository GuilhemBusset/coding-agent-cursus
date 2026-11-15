"""Rejoin a public checkpoint or run the current harness on A (offline by default)."""

import argparse
import json
import shutil
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from . import run as launcher
from .snapshot import EXERCISES, inventory, save

CHECKPOINTS = Path(__file__).resolve().parent / 'checkpoints'
NAMES = ('00-model', '01-read', '02-search')
TOOLS = ('', 'read', 'read,search')
GROUPS = ('harness', 'prompts')


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
    snapshot = exercises / 'runs/versions' / name
    save(exercises, snapshot, name)
    cache = exercises / 'runs/cache/rating-v1'
    launcher.bundle.prepare(cache, launcher.FIXED / 'runtime/fixtures/rating-support.zip')
    result = launcher.run(argparse.Namespace(
        snapshot=snapshot, settings=args.settings, mode='rating', cache=cache,
        case='a-find', tools=TOOLS[NAMES.index(args.checkpoint)], name=name,
        trial=1, seed=20261115, exercises=exercises,
        script=None if args.live else CHECKPOINTS / args.checkpoint / 'transport.json',
    ))
    output = exercises / 'runs' / name
    score = launcher.read(output / 'scorecard.json')
    comparison = dict(evidence_kind=score['evidence_kind'],
                      reference=str(cache / 'exercises/cases/a-find/reference.json'),
                      required_facts_met=score['required_facts_met'],
                      required_facts_total=score['required_facts_total'],
                      failed_assertion_ids=score['failed_assertion_ids'],
                      peer_review='pending: compare report.md with reference and inspect trace.jsonl')
    launcher.write(output / 'checkpoint-comparison.json', comparison)
    return dict(result, output=str(output), snapshot=str(snapshot), comparison=comparison)


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
    args = parser.parse_args()
    try:
        result = rejoin(args.checkpoint, args.exercises) if args.command == 'rejoin' else execute(args)
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(2, 'checkpoint failed: check inputs, choose a new run name; any backup/partial run is retained\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
