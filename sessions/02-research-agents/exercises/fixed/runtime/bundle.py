"""Hash-verified public rating support; never fall back to the working tree."""

import io
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ..snapshot import digest, encoded

CONFIG = Path(__file__).resolve().parents[1] / 'config'


def manifest() -> tuple[dict[str, Any], dict[str, str]]:
    pin = json.loads((CONFIG / 'rating-bundle.v1.json').read_text(encoding='utf-8'))
    raw = (CONFIG / 'rating-files.v1.json').read_bytes()
    if digest(raw) != pin['sha256']:
        raise ValueError('rating manifest digest mismatch')
    return pin, json.loads(raw)['files']


def verify(cache: Path) -> tuple[dict[str, Any], dict[str, str]]:
    pin, files = manifest()
    for name, expected in files.items():
        path = cache / name
        if not path.is_file():
            raise ValueError(f'rating bundle missing: {name}; run prepare')
        if path.is_symlink() or digest(path.read_bytes()) != expected:
            raise ValueError(f'rating bundle digest mismatch: {name}')
    return pin, files


def prepare(cache: Path, export: Path | None = None) -> dict[str, Any]:
    pin, files = manifest()
    if cache.exists():
        verify(cache)
        return pin
    cache.parent.mkdir(parents=True, exist_ok=True)
    # Stage and verify before publishing. TemporaryDirectory honors TMPDIR/TMP/TEMP.
    with TemporaryDirectory(prefix='s2-prepare-') as temporary:
        staging = Path(temporary) / 'bundle'
        staging.mkdir()
        archive = None
        if export and export.is_file():
            archive = zipfile.ZipFile(export)
        elif export is None:
            with urllib.request.urlopen(pin['archive_url'], timeout=60) as response:
                archive = zipfile.ZipFile(io.BytesIO(response.read()))
        try:
            for name, expected in files.items():
                if archive is not None:
                    data = archive.read(name if export else pin['archive_prefix'] + name)
                else:
                    assert export is not None
                    data = (export / name).read_bytes()
                if digest(data) != expected:
                    raise ValueError(f'rating export digest mismatch: {name}')
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            (staging / 'bundle.json').write_bytes(encoded(pin))
            verify(staging)
            shutil.copytree(staging, cache)
        finally:
            if archive:
                archive.close()
    return pin
