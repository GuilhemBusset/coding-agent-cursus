"""Evidence-only, normalized corpus access. Paths are trusted manifest data, never tool arguments."""

import json
import re
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any

MAX_SOURCE_BYTES = 1_000_000
MAX_MANIFEST_BYTES = 1_000_000
MAX_SOURCES = 100
MAX_ROWS = 1000
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')


class ToolError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ToolError('invalid_input', message)


def bounded_text(path: Path, limit: int) -> str:
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, 'evidence file exceeds size limit')
    return unicodedata.normalize('NFC', data.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n'))


class Corpus:
    def __init__(self, root: Path):
        self.root = root.resolve()
        manifest = self.root / 'corpus.json'
        require(manifest.resolve().parent == self.root, 'manifest escapes bundle')
        document = json.loads(bounded_text(manifest, MAX_MANIFEST_BYTES))
        sources = document['sources']
        require(isinstance(sources, list) and 0 < len(sources) <= MAX_SOURCES, 'invalid source inventory')
        self.sources: dict[str, dict[str, Any]] = {}
        self.paths: dict[str, Path] = {}
        for source in sources:
            sid, name = source['source_id'], source['path']
            require(isinstance(sid, str) and ID.fullmatch(sid) is not None and sid not in self.sources,
                    'invalid or duplicate source ID')
            require(isinstance(name, str) and '\\' not in name, 'invalid manifest path')
            path = PurePosixPath(name)
            require(not path.is_absolute() and len(path.parts) == 2 and path.parts[0] == 'sources'
                    and path.suffix in ('.md', '.csv') and path.name not in ('.', '..'), 'non-source manifest path')
            resolved = (self.root / name).resolve()
            require(resolved.is_relative_to(self.root / 'sources'), 'source escapes bundle')
            self.sources[sid], self.paths[sid] = source, resolved

    def source(self, source_id: Any) -> dict[str, Any]:
        require(isinstance(source_id, str) and ID.fullmatch(source_id) is not None, 'invalid source ID')
        if source_id not in self.sources:
            raise ToolError('not_found', 'unknown source ID')
        return self.sources[source_id]

    def text(self, source_id: str) -> str:
        self.source(source_id)
        path = self.paths[source_id]
        require(path.resolve().is_relative_to(self.root / 'sources'), 'source escapes bundle')
        return bounded_text(path, MAX_SOURCE_BYTES)

    def passages(self, source_id: str) -> list[dict[str, Any]]:
        text = self.text(source_id)
        passages = self.source(source_id)['passages']
        seen = set()
        for p in passages:
            require(isinstance(p['passage_id'], str) and p['passage_id'] not in seen, 'invalid passage ID')
            seen.add(p['passage_id'])
            require(type(p['start']) is int and type(p['end']) is int
                    and 0 <= p['start'] < p['end'] <= len(text), 'invalid passage offsets')
            require(text[p['start']:p['end']] == p['quote'], 'passage differs from source')
        return passages
