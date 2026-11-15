"""Prepare synthetic teaching runs without replacing either student edit directory.

Run from the session: uv run --locked python -m cursus.demos.research_loop prepare
Viewing the bundled HTML needs none of this authoring/runtime setup.
"""

import argparse
import json
import shutil
import uuid
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from exercises.fixed import checkpoint, replay

SESSION = Path(__file__).resolve().parents[2]

DEMOS = (
    ('a-gap', '00-model', 'a-find', None),
    ('b-memory', '03-memory', 'b-compare', None),
    ('c-rows', '04-audit-stop', 'c-audit', None),
    ('recovery', '04-audit-stop', 'a-find', 'transient-read'),
)
MEMBERS = (*replay.REQUIRED, 'provenance.json', 'requests.jsonl', 'memory-context.jsonl',
           'tool-results.jsonl', 'candidate-output.json', 'accounting.json',
           'scenario.json', 'transport.json')


def prepare(output: Path) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest: dict = dict(evidence_kind='synthetic', date=date.today().isoformat(), demos=[])
    with TemporaryDirectory(prefix='s2-teaching-') as temporary:
        workspace = Path(temporary) / 'exercises'
        for name, version, case, scenario in DEMOS:
            checkpoint.rejoin(version, workspace)
            result = checkpoint.execute(argparse.Namespace(
                checkpoint=version, exercises=workspace, name=name, case=case,
                scenario=scenario, live=False, snapshot=None,
                settings=checkpoint.launcher.FIXED / 'config/run.v1.json'))
            run = Path(result['output'])
            replay.seal(run, case)
            destination = output / name
            destination.mkdir()
            for member in MEMBERS:
                if (run / member).exists():
                    shutil.copyfile(run / member, destination / member)
            entry = dict(name=name, checkpoint=version, case=case, scenario=scenario,
                         quality_pass=result['quality_pass'], stop_reason=result['stop_reason'])
            manifest['demos'].append(entry)
            print(json.dumps(entry), flush=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return dict(output=str(output), evidence_kind='synthetic')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare'])
    parser.add_argument('--output', type=Path, default=SESSION / 'exercises/runs' / ('teaching-' + uuid.uuid4().hex[:8]))
    args = parser.parse_args()
    print(json.dumps(prepare(args.output)))


if __name__ == '__main__':
    main()
