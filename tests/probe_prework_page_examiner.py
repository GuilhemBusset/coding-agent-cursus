"""Independent checks of issue 24's offline page contract."""
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest
from urllib.parse import urlsplit

SESSION = Path(__file__).resolve().parents[1] / 'sessions/01-fundamentals'


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.blocks = []
        self.current = None
        self.level = 0
        self.statuses = {}
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'data-status' in attrs:
            self.statuses[attrs['data-platform']] = attrs['data-status']
        if 'data-install' in attrs:
            self.current = dict(attrs, text='', links=[], dates=[])
            self.blocks.append(self.current)
            self.level = 0
        if self.current is not None:
            if tag == 'div': self.level += 1
            if tag == 'a': self.current['links'].append(attrs.get('href', ''))
            if tag == 'time': self.current['dates'].append(attrs.get('datetime', ''))

    def handle_data(self, data):
        if self.current is not None: self.current['text'] += data

    def handle_endtag(self, tag):
        if self.current is not None and tag == 'div':
            self.level -= 1
            if self.level == 0: self.current = None


class Probe(unittest.TestCase):
    def test_D1_A4_install_coverage_and_sources(self):
        text = (SESSION / 'exercises/00-prework.html').read_text()
        page = Page(text)
        official = {'git': 'git-scm.com', 'gh': 'github.com', 'uv': 'docs.astral.sh',
                    'mise': 'mise.jdx.dev', 'claude': 'code.claude.com', 'codex': 'developers.openai.com'}
        coverage = set()
        for block in page.blocks:
            tool = block['data-tool']
            self.assertTrue(any(urlsplit(u).hostname == official[tool] for u in block['links']))
            self.assertTrue(block['dates'])
            self.assertTrue(all(date.fromisoformat(d) <= date.today() for d in block['dates']))
            self.assertRegex(block['text'], r'install|install\.sh|install\.ps1')
            coverage.update((tool, p) for p in block['data-platform'].split())
        self.assertEqual(coverage, {(t, p) for t in official for p in ('macos', 'linux', 'wsl', 'windows')})
        for required in ('unset ANTHROPIC_API_KEY', 'Remove-Item Env:ANTHROPIC_API_KEY',
                         'npm i -g codex', 'unrelated package', 'Copy it by hand'):
            self.assertIn(required, text)
        self.assertNotRegex(text, r'<(?:script|link|img)[^>]+(?:src|href)=["\']https?://')

    def test_A3_agent_part_explicit_untested_platforms(self):
        page = Page((SESSION / 'exercises/00-prework.html').read_text())
        self.assertEqual(page.statuses, dict.fromkeys(
            ('linux', 'wsl', 'macos', 'windows-powershell', 'windows-git-bash'), 'untested'))
        record = (SESSION / 'prework-verification.md').read_text()
        self.assertIn('Fixture runs on WSL2', record)
        self.assertIn('not a full real run', record)
        self.assertIn('once with only Codex', record)
        self.assertIn('To record a full run', record)
        self.assertIn('check-setup.sh', record)


if __name__ == '__main__':
    unittest.main()
