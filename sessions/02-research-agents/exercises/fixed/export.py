"""Export a clean, independently installable session (no credentials or private runs)."""

import argparse
import shutil
from pathlib import Path

SESSION = Path(__file__).resolve().parents[2]
OMIT = shutil.ignore_patterns('.git', '.venv', 'node_modules', '__pycache__', '*.pyc',
                              '.pytest_cache', '.env', '.env.*', 'runs')


def export(destination: Path) -> Path:
    destination = destination.resolve()
    if destination.is_relative_to(SESSION):
        raise ValueError('choose a destination outside the session')
    # Copy the complete public session: local locks, tests, solutions and offline pages.
    shutil.copytree(SESSION, destination, ignore=OMIT)
    runs = destination / 'exercises/runs'
    runs.mkdir()
    shutil.copyfile(SESSION / 'exercises/runs/README.md', runs / 'README.md')
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(export(args.output))
    except (OSError, ValueError) as error:
        parser.exit(2, f'export failed: {error}\n')


if __name__ == '__main__':
    main()
