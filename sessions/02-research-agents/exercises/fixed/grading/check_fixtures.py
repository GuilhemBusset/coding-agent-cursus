"""Run every public fixture in disposable directories, printing retained evidence.

From the session: uv run --locked python -m exercises.fixed.grading.check_fixtures
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
FIXED = ROOT.parent
CASES = FIXED.parent / 'cases'


def main() -> int:
    manifest = json.loads((ROOT / 'fixtures/manifest.json').read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='s2-grade-fixtures-') as temporary:
        for entry in manifest:
            run = Path(temporary) / entry['name']
            shutil.copytree(ROOT / 'fixtures' / entry['name'], run)
            result = subprocess.run([sys.executable, str(FIXED / 'grade.py'), '--run', str(run),
                                     '--case', str(CASES / entry['case']), '--policy', str(FIXED / 'config/policy.v1.json')],
                                    capture_output=True, text=True, check=False)
            print(entry['name'], 'exit', result.returncode, result.stdout.strip(), result.stderr.strip())
            if result.returncode != entry['exit_code']:
                return 1
            score = json.loads((run / 'scorecard.json').read_text(encoding='utf-8'))
            if not set(entry['failed_assertion_ids']) <= set(score['failed_assertion_ids']):
                return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
