"""Independent examiner probe for issue 45 D1."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

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

def test_d1_sheet_has_actionable_parts_and_bundled_inputs():
    p = page()
    expected = [('part-1', ('two', 'runs', 'changed')),
                ('part-2', ('three sentences', 'sampling', 'retrieval')),
                ('part-3', ('P01', 'p01_model.py', 'p01_checker.py', 'p01_contract.py')),
                ('part-4', ('/turn-in 01', '$turn-in 01', 'homework/s01/'))]
    for section, words in expected:
        text = ' '.join(p.sections[section].split()).lower()
        for word in words: assert word.lower() in text, (section, word)
    for href in p.links:
        url = urlsplit(href)
        if url.scheme or not url.path: continue
        target = (SHEET.parent / unquote(url.path)).resolve()
        assert target.is_relative_to(SESSION) and target.is_file(), href
    for command in p.blocks['Solve and check P01'].splitlines():
        script = command.split()[-1]
        assert (SESSION / script).is_file(), command
    notes = p.blocks['Template for exercises/home-notes.md']
    assert all(f'Part {n}' in notes for n in (1, 2, 3))
