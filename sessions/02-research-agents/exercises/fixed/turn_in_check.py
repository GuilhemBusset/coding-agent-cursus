"""Validate saved homework offline. Acceptance is separate from quality and live verification."""

import argparse
import json
import re
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from . import evaluate, run
from .runtime import bundle
from .schemas.validate import require, validate
from .snapshot import EXERCISES, inventory

SECRET = re.compile(r'\bsk-[A-Za-z0-9_-]{20,}|\bgh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|'
                    r'(?i:(?:api[_-]?key|authorization)\s*[=:]\s*[\"\x27]?(?:Bearer\s+)?[A-Za-z0-9_-]{20,})')
ARTIFACTS = ('config.json', 'policy.json', 'run-inputs.json', 'trace.jsonl', 'claims.json',
             'report.json', 'report.md', 'scorecard.json', 'grading.json', 'accounting.json',
             'runtime-status.json', 'peer-review.md', 'dispatches.jsonl', 'reservations.jsonl',
             'tool-results.jsonl', 'effective-settings.jsonl')


def members(root: Path) -> dict[str, str]:
    return {name: sha for name, sha in inventory(root).items() if name != 'submission.json'}


def portable(value: Any) -> Any:
    """Grader diagnostics contain absolute source links; bundles may be relocated."""
    if isinstance(value, list):
        return [portable(v) for v in value]
    if isinstance(value, dict):
        return {k: str(v).replace('\\', '/').split('/exercises/cases/')[-1] if k == 'source_path'
                else portable(v) for k, v in value.items()}
    return value


def hygiene(exercises: Path) -> None:
    # These are precisely the editable/submitted inputs; supplied public support is
    # checked separately by its pin. Never echo a matched value into diagnostics.
    for root in (exercises / 'harness', exercises / 'prompts', exercises / 'runs/submission'):
        inventory(root)  # refuses links, including directory links
        for path in root.rglob('*'):
            if path.is_file():
                require(not path.name.startswith('.env'), 'environment file in submission')
                require(not SECRET.search(path.read_bytes().decode('utf-8', errors='replace')), 'credential in submission')
    for path in exercises.iterdir():
        if path.is_file():
            require(not path.name.startswith('.env'), 'environment file in exercises')
            require(not SECRET.search(path.read_bytes().decode('utf-8', errors='replace')), 'credential in exercise file')


def comparison(source: Path, kind: str) -> dict[str, Any]:
    require(all((source / name).is_file() for name in ('comparison.md', 'before.md', 'after.md')), 'missing comparison reports')
    shared = run.read(source / 'shared.json')
    require(shared['schema_version'] == '1.0' and shared['mode'] == 'submission', 'submission mode required')
    require(shared['experiment_type'] == kind, 'wrong experiment type')
    require(shared['evidence_kind'] in ('synthetic', 'captured_live'), 'invalid evidence kind')
    require(shared['settings'] == run.settings(run.FIXED / 'config/run.v1.json'), 'use the same public configuration')
    bundle.verify(source / 'cache')
    require(shared['schedule'] == evaluate.schedule('submission', source / 'cache'), 'missing or changed trial schedule')
    require(run.read(source / 'public-manifest.json') == run.read(run.FIXED / 'config/public/manifest.json'), 'public schedule changed')
    versions = {role: evaluate.version(source / 'versions' / role) for role in evaluate.ROLES}
    frozen = 'prompts' if kind == 'harness' else 'harness'
    require(versions['baseline']['files'][frozen] == versions['candidate']['files'][frozen], 'frozen variable changed')
    require(run.read(source / 'settings.json') == shared['settings'], 'settings artifact mismatch')
    spec = run.read(source / 'experiment.json')
    require(all(spec[k] == shared[k] for k in ('schema_version', 'mode', 'experiment_type')), 'experiment mismatch')
    require(('scripts' in spec) == (shared['evidence_kind'] == 'synthetic'), 'transport label mismatch')
    if shared['evidence_kind'] == 'synthetic':
        for case in ('A', 'B', 'C'):
            run.read(source / 'scripts' / (case + '.json'))
    expected_runs = {f'{role}-{i:02}' for role in evaluate.ROLES for i in range(1, len(shared['schedule']) + 1)}
    require({p.name for p in (source / 'runs').iterdir()} == expected_runs, 'missing or extra trials')
    with TemporaryDirectory(prefix='s2-submission-') as temporary:
        work = Path(temporary) / 'comparison'
        shutil.copytree(source, work)
        for name in sorted(expected_runs):
            original, copied = source / 'runs' / name, work / 'runs' / name
            require(all((original / file).is_file() for file in ARTIFACTS), 'incomplete attempt artifacts')
            for file in original.iterdir():
                if file.suffix == '.json':
                    run.read(file)
                elif file.suffix == '.jsonl':
                    evaluate.lines(file)
            for schema in ('claims', 'report'):
                validate(schema, run.read(original / (schema + '.json')))
            config = run.read(original / 'config.json')
            require(config['evidence_kind'] == shared['evidence_kind'], 'evidence label mismatch')
            slot = shared['schedule'][int(name.rsplit('-', 1)[1]) - 1]
            # Regrade using only hash-verified pinned Python support in a fresh
            # interpreter. Never execute a submitted harness or call a provider.
            run.grade(copied, source / 'cache', source / 'cache/exercises/cases' / slot['case'])
            for file in ('scorecard.json', 'grading.json', 'accounting.json'):
                require(portable(run.read(copied / file)) == portable(run.read(original / file)), 'independent ' + file + ' mismatch')
        result = evaluate.collect(work)
        require(result['before']['status'] == result['after']['status'] == 'complete', 'incomplete or incompatible evidence')
        for file in ('comparison.json', 'before.json', 'after.json'):
            require(run.read(work / file) == run.read(source / file), 'independent comparison mismatch')
    return dict(quality_pass=result['after']['quality_gates_pass'], evidence_kind=shared['evidence_kind'],
                recommendation=result['recommendation']['choice'])


def check(exercises: Path, seal: bool = False, live_status: str = 'unavailable') -> dict[str, Any]:
    root = exercises / 'runs/submission'
    hygiene(exercises)
    require(bool((exercises / 'home-notes.md').read_text(encoding='utf-8').strip()), 'missing homework notes')
    require(bool((root / 'peer-audit.md').read_text(encoding='utf-8').strip()), 'missing peer audit or pending status')
    results = {kind: comparison(root / kind, kind) for kind in ('harness', 'prompt')}
    if seal:
        run.write(root / 'submission.json', dict(schema_version='1.0', live_status=live_status, files=members(root)))
    manifest = run.read(root / 'submission.json')
    require(set(manifest) == {'schema_version', 'live_status', 'files'} and manifest['schema_version'] == '1.0', 'invalid submission schema')
    require(manifest['live_status'] in ('available', 'unavailable'), 'invalid live status')
    require(manifest['live_status'] != 'available' or any(r['evidence_kind'] == 'captured_live' for r in results.values()), 'live availability needs captured-live evidence')
    require(manifest['files'] == members(root), 'submission artifact hash mismatch')
    # Even captured-live is an assertion of origin, pending independent/live and
    # human prose review; this structural gate never certifies live performance.
    return dict(accepted=True, comparisons=results, live_status=manifest['live_status'],
                live_verification='unverified', live_pass=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exercises', type=Path, default=EXERCISES)
    parser.add_argument('--seal', action='store_true', help='validate then record hashes after the peer audit')
    parser.add_argument('--live-status', choices=('available', 'unavailable'), default='unavailable')
    args = parser.parse_args()
    try:
        result = check(args.exercises.resolve(), args.seal, args.live_status)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        print(json.dumps(dict(accepted=False, error=str(error) if not isinstance(error, OSError) else 'missing/unreadable artifact')))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
