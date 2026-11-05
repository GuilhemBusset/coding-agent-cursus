"""Public track labels must agree with the verification record, including outstanding live runs."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_track_status_matches_and_live_runs_remain_explicit():
    docs = (ROOT / 'setup/student/README.md').read_text()
    record = (ROOT / 'setup/student/verification.md').read_text()
    tracks = ('Windows (PowerShell)', 'Windows with WSL 2', 'macOS', 'Debian / Ubuntu', 'Fedora', 'Arch', 'Other Linux')
    for track in tracks:
        row = next(line for line in record.splitlines() if line.startswith('| ' + track + ' |'))
        cells = [v.strip() for v in row.split('|')]
        section = docs.split('### ' + track + '\n', 1)[1].split('\n### ', 1)[0]
        assert f'**Status:** CI: {cells[2]}. Live run: {cells[3]}.' in section
        assert cells[3] in ('untested', 'tested live')
    assert 'How to record a live run' in record and 'result: PASS' in record
