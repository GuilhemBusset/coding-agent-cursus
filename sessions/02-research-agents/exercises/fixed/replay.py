"""Validate and regrade a saved research run offline; always emits replay evidence."""

import argparse
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from .grading.engine import grade_run
from .schemas.validate import require, summarize_scorecards, summarize_trace, validate
from .snapshot import EXERCISES, digest, inventory

REQUIRED = ('config.json', 'policy.json', 'claims.json', 'report.json', 'report.md', 'trace.jsonl', 'scorecard.json')


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def case_path(relative: str) -> Path:
    path = (EXERCISES / 'cases' / relative).resolve()
    require(path.is_relative_to((EXERCISES / 'cases').resolve()), 'case outside public cases')
    return path


def seal(run: Path, case: str) -> None:
    """Integrity envelope after capture/sanitization, not authentication of live origin."""
    config = read(run / 'config.json')
    validate('run-config', config)
    require(config['evidence_kind'] in ('synthetic', 'captured_live'), 'only original runs can be sealed')
    events = [json.loads(line) for line in (run / 'trace.jsonl').read_text(encoding='utf-8').splitlines()]
    summarize_trace(events, config['run_id'])
    members = list(REQUIRED) + [p for p in ('scenario.json', 'transport.json') if (run / p).exists()]
    write(run / 'provenance.json', dict(version='1.0', source_run_id=config['run_id'], evidence_kind=config['evidence_kind'],
        case=case, case_files=inventory(case_path(case)), files={name: digest((run / name).read_bytes()) for name in members},
        claim='Integrity since sealing; origin label is a capture assertion, not proof of live compatibility.'))


def replay(source: Path, output: Path) -> dict[str, Any]:
    provenance = read(source / 'provenance.json')
    require(provenance['evidence_kind'] in ('synthetic', 'captured_live'), 'invalid source evidence kind')
    require(set(REQUIRED) <= set(provenance['files']), 'missing provenance members')
    for name, sha in provenance['files'].items():
        require(Path(name).name == name, 'invalid provenance member')
        require(digest((source / name).read_bytes()) == sha, f'artifact hash mismatch: {name}')
    config = read(source / 'config.json')
    validate('run-config', config)
    require(config['run_id'] == provenance['source_run_id'] and config['evidence_kind'] == provenance['evidence_kind'], 'source provenance identity')
    case = case_path(provenance['case'])
    require(inventory(case) == provenance['case_files'], 'public case hash mismatch')
    require(digest((source / 'policy.json').read_bytes()) == config['policy_sha256'], 'policy hash mismatch')
    events = [json.loads(line) for line in (source / 'trace.jsonl').read_text(encoding='utf-8').splitlines()]
    summary = summarize_trace(events, config['run_id'])
    original_score = read(source / 'scorecard.json')
    validate('scorecard', original_score)
    require(all(original_score[k] == v for k, v in summary.items()), 'source scorecard accounting mismatch')
    output.mkdir(parents=True, exist_ok=False)
    for name in ('config.json', 'trace.jsonl', 'provenance.json'):
        shutil.copyfile(source / name, output / ('source-' + name))
    for name in ('policy.json', 'report.md'):
        shutil.copyfile(source / name, output / name)
    original_id = config['run_id']
    config.update(run_id='replay-' + uuid.uuid4().hex, evidence_kind='replay', replay_of=original_id)
    config['workspace']['workspace_id'] = 'workspace-' + uuid.uuid4().hex
    write(output / 'config.json', config)
    for name in ('claims.json', 'report.json'):
        artifact = read(source / name)
        artifact['run_id'] = config['run_id']
        write(output / name, artifact)
    for event in events:
        event['run_id'] = config['run_id']
        if event['type'] == 'tool_invocation':
            for key in ('input', 'result'):
                event[key]['run_id'] = config['run_id']
    (output / 'trace.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
    summary = summarize_trace(events, config['run_id'])
    write(output / 'accounting.json', summary)
    score = grade_run(output, case, output / 'policy.json')
    aggregate = summarize_scorecards([score])
    write(output / 'efficiency.json', aggregate)
    write(output / 'provenance.json', dict(evidence_kind='replay', replay_of=original_id,
        source_evidence_kind=provenance['evidence_kind'], source_config_sha256=provenance['files']['config.json'],
        source_trace_sha256=provenance['files']['trace.jsonl'], source_provenance_sha256=digest((source / 'provenance.json').read_bytes()),
        limitation='Replay supports inspection and offline editing; it cannot certify live autonomous research.'))
    return dict(run_id=config['run_id'], evidence_kind='replay', source_evidence_kind=provenance['evidence_kind'],
                replay_of=original_id, stop_reason=score['stop_reason'], model_attempts=score['model_attempts'],
                service_errors=score['service_errors'], total_tokens=score['total_tokens'], quality_pass=score['quality_pass'],
                efficiency_status=aggregate['efficiency_status'])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--seal', action='store_true', help='seal an original run AFTER capture/sanitization review')
    parser.add_argument('--case', help='public path relative to exercises/cases; required with --seal')
    args = parser.parse_args()
    try:
        if args.seal:
            require(bool(args.case) and args.out is None, '--seal needs --case and no --out')
            seal(args.run, args.case)
            result = dict(sealed=True, evidence_kind=read(args.run / 'config.json')['evidence_kind'])
        else:
            require(args.out is not None and args.case is None, 'replay needs --out')
            result = replay(args.run, args.out)
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(2, 'invalid replay source, integrity mismatch, or output already exists\n')
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
