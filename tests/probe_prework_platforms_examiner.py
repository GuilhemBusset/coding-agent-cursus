"""A3 agent work: explicit platform limitations and owner-run instructions."""
from pathlib import Path
import re

session = Path(__file__).resolve().parents[1] / 'sessions/01-fundamentals'
page = (session / 'exercises/00-prework.html').read_text()
record = (session / 'prework-verification.md').read_text()
for platform in ('linux', 'wsl', 'macos', 'windows-powershell', 'windows-git-bash'):
    assert re.search(r'data-status="untested" data-platform="' + platform + '"', page), platform
for phrase in ('Fixture runs on WSL2', 'not a full real run', 'To record a full run',
               'once with only', 'Claude Code', 'once with only Codex', 'check-setup.sh'):
    assert phrase in record, phrase
print('PASS: limitations are explicit; full native Linux/WSL evidence remains pending')
