"""A complete truthful submission whose attempts make no tool call must be accepted (D5/A2)."""

import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from test_standalone import SESSION, command, offline


def test_complete_submission_without_tool_calls_is_accepted_unverified():
    assert command(['node', '--version'], SESSION).stdout.strip() == 'v24.15.0'
    if not (SESSION / 'node_modules/@earendil-works/pi-agent-core/package.json').exists():
        npm = shutil.which('npm')
        assert npm
        command([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], SESSION)
    with TemporaryDirectory(prefix='s2-tool-free-submission-') as temporary:
        root = Path(temporary)
        exercises = root / 'exercises'
        exercises.mkdir()
        # The public completed checkpoint 00 (a model call, no tools) is a legitimate,
        # runnable harness. Follow the README: save versions, configure, submission mode.
        checkpoint = SESSION / 'exercises/fixed/checkpoints/00-model'
        for group in ('harness', 'prompts'):
            shutil.copytree(checkpoint / group, exercises / group)
        versions = root / 'versions'
        offline('snapshot', '--exercises', exercises, '--name', 'h-before', '--output', versions / 'h-before')
        with (exercises / 'harness/main.ts').open('a', encoding='utf-8') as stream:
            stream.write('\n// one harness change\n')
        offline('snapshot', '--exercises', exercises, '--name', 'h-after', '--output', versions / 'h-after')
        offline('snapshot', '--exercises', exercises, '--name', 'p-before', '--output', versions / 'p-before')
        with (exercises / 'prompts/system.md').open('a', encoding='utf-8') as stream:
            stream.write('\nCite every factual claim.\n')
        offline('snapshot', '--exercises', exercises, '--name', 'p-after', '--output', versions / 'p-after')
        submission = exercises / 'runs/submission'
        for kind, before, after in (('harness', 'h-before', 'h-after'), ('prompt', 'p-before', 'p-after')):
            spec = root / (kind + '.json')
            offline('examples.workflow', 'configure', kind, '--baseline', versions / before,
                    '--candidate', versions / after, '--output', spec)
            data = json.loads(spec.read_text(encoding='utf-8'))
            data['mode'] = 'submission'
            spec.write_text(json.dumps(data), encoding='utf-8')
            offline('evaluate', 'compare', '--experiment', spec, '--output', submission / kind, codes=(0, 1))
            result = json.loads((submission / kind / 'comparison.json').read_text(encoding='utf-8'))
            # The comparison itself is complete: every scheduled attempt ran and was graded.
            assert result['before']['status'] == result['after']['status'] == 'complete'
        (exercises / 'home-notes.md').write_text('Synthetic outage homework; peer review pending.\n', encoding='utf-8')
        (submission / 'peer-audit.md').write_text('Pending: no human peer available.\n', encoding='utf-8')
        gate = offline('turn_in_check', '--exercises', exercises, '--seal', codes=(0, 1))
        verdict = json.loads(gate.stdout)
        assert verdict['accepted'], verdict
        assert verdict['live_pass'] is False and verdict['live_verification'] == 'unverified'
