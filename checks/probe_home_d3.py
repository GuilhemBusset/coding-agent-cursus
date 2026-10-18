"""Independent examiner probe for issue 45 D3."""

from html.parser import HTMLParser
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

SESSION = ROOT / 'sessions/01-fundamentals'

SHEET = SESSION / 'exercises/home.html'

PACK = SESSION / 'exercises/homework-p01'

class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sections = {}; self.blocks = {}; self.links = []
        self.section = None; self.pre = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'section':
            self.section = attrs.get('id'); self.sections[self.section] = ''
        if tag == 'pre':
            self.pre = attrs.get('aria-label'); self.blocks[self.pre] = ''
        if 'href' in attrs: self.links.append(attrs['href'])
    def handle_data(self, text):
        if self.section: self.sections[self.section] += text
        if self.pre: self.blocks[self.pre] += text
    def handle_endtag(self, tag):
        if tag == 'section': self.section = None
        if tag == 'pre': self.pre = None

def page():
    result = Page(); result.feed(SHEET.read_text(encoding='utf-8')); return result

def run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=50)

def test_d3_both_agent_routes_share_the_same_proof():
    p = page()
    for section in ('start', 'part-1', 'part-4'):
        assert all(name in p.sections[section] for name in ('Claude Code', 'Codex'))
    assert p.blocks['Turn in with Claude Code'].strip() == '/turn-in 01'
    assert p.blocks['Turn in with Codex'].strip() == '$turn-in 01'
    assert p.blocks['Turn in from a terminal'].strip() == 'bash scripts/turn-in.sh 01'
    for demo in ('Sampling', 'Strawberry'):
        assert p.blocks[f'{demo} demo in Claude Code'].strip().startswith('claude -p ')
        assert p.blocks[f'{demo} demo in Codex'].strip().startswith('codex exec ')
    assert 'same for both agents' in p.sections['part-3']
    contract = run(['uv', 'run', 'pytest', '--collect-only', '-q',
                    'exercises/homework-p01/p01_contract.py'], SESSION)
    assert contract.returncode == 0, contract.stdout + contract.stderr
    assert 'test_status_mapping_contract' in contract.stdout and 'test_optimality_contract' in contract.stdout, contract.stdout
