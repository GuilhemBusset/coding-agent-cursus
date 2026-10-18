"""Evidence scope must stay honest and refer to the scripts actually delivered."""
from pathlib import Path
import hashlib
import re

SESSION = Path(__file__).resolve().parents[1] / 'sessions/01-fundamentals'


def test_platform_limits_and_current_script_evidence():
    page = (SESSION / 'exercises/00-prework.html').read_text()
    record = (SESSION / 'prework-verification.md').read_text()
    for name in ('check_setup.py', 'check-setup.sh', 'check-setup.ps1'):
        digest = hashlib.sha256((SESSION / 'exercises' / name).read_bytes()).hexdigest()
        assert digest in record, name
    for platform in ('linux', 'macos', 'windows-powershell', 'windows-git-bash'):
        assert re.search(r'<li\b[^>]*data-status="untested"[^>]*data-platform="' + platform + '"', page)
    assert 'GitHub, its login and the network were local stand-ins' in page
    for phrase in ('To record a full run', 'native Linux is the owner', 'once with only Claude Code', 'once with only Codex', 'prework_live_agents.py', '2026-10-18'):
        assert phrase in record
