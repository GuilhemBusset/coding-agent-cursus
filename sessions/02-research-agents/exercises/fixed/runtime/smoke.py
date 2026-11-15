"""Offline CLI smoke; print evidence before cleaning every temporary artifact."""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from ..run import SESSION

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, help='optionally save representative sanitized artifacts')
    args = parser.parse_args()
    with TemporaryDirectory(prefix='s2-smoke-') as temporary:
        root = Path(temporary)
        exercises = root / 'student work with spaces/exercises'
        (exercises / 'harness').mkdir(parents=True)
        (exercises / 'prompts').mkdir()
        shutil.copyfile(FIXTURES / 'smoke-harness.ts', exercises / 'harness/main.ts')
        (exercises / 'prompts/system.md').write_text('Read the public local evidence. Cite sources.', encoding='utf-8')
        commands = [
            ['run', 'prepare', '--cache', root / 'cache', '--export', FIXTURES / 'rating-support.zip'],
            ['snapshot', '--exercises', exercises, '--name', 'baseline-v1', '--output', root / 'baseline-v1'],
            ['run', 'run', '--exercises', exercises, '--snapshot', root / 'baseline-v1', '--cache', root / 'cache',
             '--script', FIXTURES / 'smoke-transport.json', '--name', 'offline-smoke'],
        ]
        for module, *parameters in commands:
            result = subprocess.run([sys.executable, '-m', 'exercises.fixed.' + str(module), *map(str, parameters)],
                                    cwd=SESSION, capture_output=True, text=True, timeout=45)
            print(result.stdout, end='')
            if result.returncode:
                print(result.stderr)
                raise SystemExit(result.returncode)
        output = exercises / 'runs/offline-smoke'
        accounting = json.loads((output / 'accounting.json').read_text(encoding='utf-8'))
        assert accounting['model_attempts'] == 2 and accounting['tool_invocations'] == 1 and accounting['total_tokens'] == 240
        print('SYNTHETIC offline boundary evidence; no live/API/platform certification.')
        for name in ('config.json', 'trace.jsonl', 'runtime-status.json', 'accounting.json'):
            print(name + ':\n' + (output / name).read_text(encoding='utf-8'))
            if args.capture:
                args.capture.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(output / name, args.capture / name)


if __name__ == '__main__':
    main()
