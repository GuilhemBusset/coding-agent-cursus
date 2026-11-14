"""Portable CLI launcher for the session-local offline grading module."""

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('run', 'case', 'policy'):
        parser.add_argument('--' + option, required=True, type=Path)
    args = parser.parse_args()
    # Resolve caller paths before using the standalone session as the module root.
    return subprocess.call([sys.executable, '-m', 'exercises.fixed.grading.engine',
                            '--run', str(args.run.resolve()), '--case', str(args.case.resolve()),
                            '--policy', str(args.policy.resolve())], cwd=Path(__file__).resolve().parents[2])


if __name__ == '__main__':
    raise SystemExit(main())
