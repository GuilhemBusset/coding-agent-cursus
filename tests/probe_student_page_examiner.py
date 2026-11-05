"""Every pre-work platform starts with the repository bootstrap, retaining manual fallbacks."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_prework_starts_with_four_bootstraps_and_keeps_manual_tools():
    page = (ROOT / 'sessions/01-fundamentals/exercises/00-prework.html').read_text()
    install = page[page.index('<h2 id="install-title">'):]
    first_manual = install.index('data-install')
    blocks = re.findall(r'<div[^>]*data-setup[^>]*data-platform="([^"]+)"[^>]*>(.*?)</div>', install, re.DOTALL)
    assert {p for p, _ in blocks} == {'windows', 'wsl', 'macos', 'linux'}
    for platform, body in blocks:
        script = 'install.ps1' if platform == 'windows' else 'install.sh'
        assert f'https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/{script}' in body
        assert install.index(body) < first_manual
    for tool in ('git', 'gh', 'uv', 'mise', 'claude', 'codex'):
        assert f'data-tool="{tool}"' in install[first_manual:]
