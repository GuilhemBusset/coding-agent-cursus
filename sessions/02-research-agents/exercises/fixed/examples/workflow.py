"""Prepare controlled comparisons or rejoin a public completed experiment version."""

import argparse
import json
import shutil
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from ..snapshot import EXERCISES, encoded, inventory, verify

EXAMPLES = Path(__file__).resolve().parent
VERSIONS = ('harness-baseline', 'harness-candidate', 'prompt-vague', 'prompt-structured',
            'prompt-vague-paraphrase', 'prompt-structured-paraphrase')


def configure(kind: str, baseline: Path, candidate: Path, output: Path) -> dict:
    """Keep the public controls/scripts; substitute only the two saved versions."""
    for path in (baseline, candidate):
        verify(path)
    spec = json.loads((EXAMPLES / (kind + '.json')).read_text(encoding='utf-8'))
    for key in ('settings', 'rating_export'):
        spec[key] = str((EXAMPLES / spec[key]).resolve())
    spec['scripts'] = {case: str((EXAMPLES / path).resolve()) for case, path in spec['scripts'].items()}
    spec.update(baseline=str(baseline.resolve()), candidate=str(candidate.resolve()))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(encoded(spec))
    return dict(experiment=str(output.resolve()), evidence_kind='synthetic')


def rejoin(name: str, exercises: Path) -> dict:
    source = EXAMPLES / 'versions' / name
    verify(source)
    # Stage both replacements, then back up both editable trees before replacing.
    with TemporaryDirectory(prefix='s2-experiment-rejoin-') as temporary:
        staging = Path(temporary)
        for group in ('harness', 'prompts'):
            shutil.copytree(source / group, staging / group)
            inventory(exercises / group)
        backup = exercises / 'runs/backups' / (name + '-' + uuid.uuid4().hex)
        backup.mkdir(parents=True)
        for group in ('harness', 'prompts'):
            if (exercises / group).exists():
                shutil.copytree(exercises / group, backup / group)
        for group in ('harness', 'prompts'):
            if (exercises / group).exists():
                shutil.rmtree(exercises / group)
            shutil.copytree(staging / group, exercises / group)
    return dict(version=name, backup=str(backup.resolve()), evidence_kind='synthetic')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    restore = commands.add_parser('rejoin')
    restore.add_argument('version', choices=VERSIONS)
    restore.add_argument('--exercises', type=Path, default=EXERCISES)
    prepare = commands.add_parser('configure')
    prepare.add_argument('kind', choices=('harness', 'prompt', 'paraphrases'))
    prepare.add_argument('--baseline', required=True, type=Path)
    prepare.add_argument('--candidate', required=True, type=Path)
    prepare.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = rejoin(args.version, args.exercises) if args.command == 'rejoin' else configure(
            args.kind, args.baseline, args.candidate, args.output)
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(2, 'experiment preparation failed: check snapshots and use a new output path; backups are retained\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
