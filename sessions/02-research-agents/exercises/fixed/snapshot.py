"""Save and verify harness/prompt versions. Run with the session's `uv run`."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

EXERCISES = Path(__file__).resolve().parent.parent


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def inventory(root: Path) -> dict[str, str]:
    files = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('symlinks are not snapshot inputs')
        if path.is_file():
            files[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return files


def verify(root: Path) -> dict[str, Any]:
    manifest = json.loads((root / 'snapshot.json').read_text(encoding='utf-8'))
    actual = {group: inventory(root / group) for group in ('harness', 'prompts')}
    if actual != manifest['files'] or digest(encoded(actual)) != manifest['sha256']:
        raise ValueError('snapshot digest mismatch')
    return manifest


def save(exercises: Path, destination: Path, name: str) -> dict[str, Any]:
    if not name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-' for c in name) or not name[0].isalnum():
        raise ValueError('snapshot name must be an identifier')
    destination.mkdir(parents=True, exist_ok=False)
    try:
        for group in ('harness', 'prompts'):
            inventory(exercises / group)  # reject symlinks before copying
            shutil.copytree(exercises / group, destination / group)
        files = {group: inventory(destination / group) for group in ('harness', 'prompts')}
        manifest = dict(schema_version='1.0', snapshot_id=name, files=files, sha256=digest(encoded(files)))
        (destination / 'snapshot.json').write_bytes(encoded(manifest))
        return verify(destination)
    except Exception:
        shutil.rmtree(destination)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exercises', type=Path, default=EXERCISES)
    parser.add_argument('--name', required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        result = save(args.exercises, args.output or args.exercises / 'runs' / 'versions' / args.name, args.name)
    except (OSError, ValueError):
        parser.exit(2, 'snapshot failed: destination exists, input missing, or invalid snapshot\n')
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
