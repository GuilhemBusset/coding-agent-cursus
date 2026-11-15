"""Run an announced synthetic fault through fixed dispatch and grading, offline."""

import argparse
import json
import shutil
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .. import run as launcher
from .. import snapshot
from ..replay import seal
from .transport import response

FIXED = launcher.FIXED
PUBLIC = FIXED / 'config/public'
MANIFEST = launcher.read(PUBLIC / 'manifest.json')
SCENARIOS = [s['scenario_id'] for s in MANIFEST['fault_scenarios']]


def scenario(name: str) -> dict[str, Any]:
    if name not in SCENARIOS:
        raise ValueError('unknown public scenario')
    return launcher.read(PUBLIC / 'faults' / (name + '.json'))


def inputs(name: str) -> tuple[str, int, dict[str, Any], list[dict[str, Any]], str]:
    """Inspectably construct schedules, real corpus reads and explicit synthetic outputs."""
    spec = scenario(name)
    selected = MANIFEST['variants'][2 if name == 'absent-usage' else 0]
    case = selected['path'].removeprefix('cases/')
    corpus = launcher.read(FIXED.parent / selected['path'] / 'corpus.json')
    source = next(s for s in corpus['sources'] if s['passages'])
    passage = source['passages'][0]
    args = dict(source_id=source['source_id'], start=passage['start'], end=passage['end'])
    options = launcher.read(FIXED / 'config/run.v1.json')
    fault: dict[str, Any] = dict(scenario_id=name, spec_sha256=snapshot.digest((PUBLIC / 'faults' / (name + '.json')).read_bytes()),
                 schedule=dict(trigger=spec['trigger'], responses=spec['responses'], selected_read=args,
                               preconditions=spec['preconditions']))
    partial = dict(claims=[dict(claim_id='unfinished', kind='factual', assertion=dict(subject='research', predicate='result',
        type='string', value='not-established', unit=None), support_status='unknown', evidence=[], reference_fact_ids=[],
        experiment_ids=[], supersedes_claim_ids=[])], claim_anchors=[dict(claim_id='unfinished', anchor='claim-unfinished')],
        markdown='<a id="claim-unfinished"></a>\nEvidence is incomplete; no research conclusion is established.\n')
    body = 'await api.model();'
    steps = [response()]
    if name in ('transient-read', 'missing-source'):
        if name == 'missing-source':
            args = spec['trigger']['arguments']
        steps = [response([args]), response([args])]
        body = 'await recoverRead(api);'
    elif name == 'repeated-retrieval':
        steps = [response([args])] * 3
        body = '''const seen = new Set(); let unchanged = 0;
  for (;;) {
    await api.model(); const results = await api.tools();
    for (const r of results) {
      const key = JSON.stringify(r.data);
      if (seen.has(key)) unchanged++; else { seen.add(key); unchanged = 0; }
    }
    if (unchanged >= 2) return { ...partial, stop_reason: 'no_progress' };
  }'''
    elif name == 'malformed-tool-arguments':
        steps = [response([spec['trigger']['arguments']])]
        body = "await api.model(); await api.tools(); return { claims: [], claim_anchors: [], markdown: '' };"
    elif name == 'malformed-output':
        steps = [response(text=spec['responses'][0]['raw_output'])]
        body = "const m = await api.model(); const raw = m.content.filter(c => c.type === 'text').map(c => c.text).join(''); try { return JSON.parse(raw); } catch { return { raw_output: raw }; }"
    elif name in ('timeout', 'rate-limit'):
        options['connection']['timeout_ms'] = 1000
        steps = [dict(stall=True)] * 2 if name == 'timeout' else [dict(status=429, body='{"error":{"message":"synthetic rate limit"}}')] * 2
    elif name == 'model-budget':
        steps *= 12
        body = 'for (let i = 0; i < 13; i++) await api.model();'
    elif name == 'tool-budget':
        steps = [response([args] * 21)]
        body = 'await api.model(); await api.tools();'
    elif name == 'token-budget':
        # Padding places the declared 30,000 synthetic tokens inside the independently
        # journalled reservation. No counters are seeded and policy limits stay fixed.
        options['connection']['settings']['max_output_tokens'] = 8192
        steps = [response(input_tokens=21808, output_tokens=8192)]
        body = "api.addMessage('x'.repeat(4534)); await api.model(); await api.model();"
        fault['schedule']['reservation_padding_characters'] = 4534
    elif name == 'absent-usage':
        fixture = launcher.read(FIXED.parent / selected['path'] / 'examples.json')['positive'][0]['value']
        # The public example is an explicitly scripted output, not a model finding.
        partial['claims'] = fixture['claims']
        partial['claim_anchors'] = [dict(claim_id=c['claim_id'], anchor='claim-' + c['claim_id']) for c in fixture['claims']]
        partial['markdown'] = '\n'.join('<a id="claim-' + c['claim_id'] + '"></a>\n' + json.dumps(c['assertion']) for c in fixture['claims'])
        steps = [response(unknown=True)]
        body = 'await api.model(); api.saveOutput(partial); await api.model();'
    code = "import { recoverRead } from './recovery.ts';\nconst partial = " + json.dumps(partial) + ';\nexport async function run(api: any) {\n' + body + '\nreturn partial;\n}\n'
    return case, selected['seed'], dict(options=options, fault=fault), steps, code


def execute(name: str, output: Path) -> dict[str, Any]:
    case, seed, config, steps, code = inputs(name)
    with TemporaryDirectory(prefix='s2-fault-') as temporary:
        root = Path(temporary)
        (root / 'harness').mkdir()
        (root / 'prompts').mkdir()
        (root / 'prompts/research.md').write_text('Public synthetic fault exercise; inspect evidence and retain failures.\n', encoding='utf-8')
        shutil.copyfile(FIXED / 'faults/recovery.ts', root / 'harness/recovery.ts')
        launcher.write(root / 'transport.json', steps)
        launcher.write(root / 'settings.json', config['options'])
        (root / 'harness/main.ts').write_text(code, encoding='utf-8')
        snapshot.save(root, root / 'saved', 'public-fault-' + name)
        args = argparse.Namespace(snapshot=root / 'saved', settings=root / 'settings.json', mode='development',
            exercises=FIXED.parent, case=case, tools=None, name='synthetic-' + name + '-' + uuid.uuid4().hex,
            trial=1, seed=seed, script=root / 'transport.json', fault=config['fault'], out=output)
        result = launcher.run(args)
        shutil.copyfile(root / 'transport.json', output / 'transport.json')
        launcher.write(output / 'scenario.json', scenario(name))
        seal(output, case)
        return dict(result, evidence_kind='synthetic', scenario_id=name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=SCENARIOS, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args.scenario, args.out.resolve())))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
