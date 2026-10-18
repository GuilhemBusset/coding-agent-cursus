"""Independent content coverage and dated official-source links."""
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import urlsplit

PAGE = Path(__file__).resolve().parents[1] / 'sessions/01-fundamentals/exercises/00-prework.html'


class Installs(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.blocks = []
        self.depth = 0
        self.current = None
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div':
            self.depth += 1
            if 'data-install' in attrs:
                self.current = {'attrs': attrs, 'depth': self.depth, 'links': [], 'dates': [], 'text': []}
                self.blocks.append(self.current)
        if self.current and tag == 'a':
            self.current['links'].append(attrs.get('href', ''))
        if self.current and tag == 'time':
            self.current['dates'].append(attrs.get('datetime', ''))

    def handle_endtag(self, tag):
        if tag == 'div':
            if self.current and self.depth == self.current['depth']:
                self.current = None
            self.depth -= 1

    def handle_data(self, text):
        if self.current:
            self.current['text'].append(text)


def test_install_coverage_and_troubleshooting():
    source = PAGE.read_text()
    blocks = Installs(source).blocks
    coverage = {(b['attrs']['data-tool'], p) for b in blocks for p in b['attrs']['data-platform'].split()}
    assert {(tool, platform) for tool in ('git', 'gh', 'uv', 'mise', 'claude', 'codex') for platform in ('macos', 'linux', 'wsl', 'windows')} <= coverage
    for text in ('npm i -g codex', 'unrelated package', 'unset ANTHROPIC_API_KEY', 'Remove-Item Env:ANTHROPIC_API_KEY', 'Copy it by hand', 'https://claude.ai/install.sh', 'https://claude.ai/install.ps1'):
        assert text in source


def test_each_install_has_dated_official_source():
    domains = {'git': {'git-scm.com'}, 'gh': {'github.com'}, 'uv': {'docs.astral.sh'}, 'mise': {'mise.jdx.dev'}, 'claude': {'code.claude.com'}, 'codex': {'developers.openai.com', 'github.com'}}
    blocks = Installs(PAGE.read_text()).blocks
    assert blocks
    for b in blocks:
        assert b['dates'] and all(date.fromisoformat(d) <= date.today() for d in b['dates'])
        assert any(urlsplit(link).hostname in domains[b['attrs']['data-tool']] for link in b['links'])


def test_required_prereading_and_selected_chapters():
    source = PAGE.read_text().split('<section id="reading"', 1)[1].split('</section>', 1)[0]
    for text in ('LPZh9BOjkQs', 'EWvNQjAaOHw', 'claude-code-101', 'academy.openai.com', 'get-started-with-codex'):
        assert text in source
    assert len(set(re.findall(r'EWvNQjAaOHw&amp;t=(\d+)s', source))) >= 2
