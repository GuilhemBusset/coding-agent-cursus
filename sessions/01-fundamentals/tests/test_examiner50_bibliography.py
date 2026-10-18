"""Independent D2 witness using the actual delivered bibliography."""
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

SESSION = Path(__file__).resolve().parents[1]

class Bibliography(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.groups = []
        self.entries = []
        self.entry = None
        self.feed(text)
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'section' and 'data-act' in attrs:
            self.groups.append({'id': attrs.get('id'), 'links': []})
        if tag == 'li' and 'data-source' in attrs:
            self.entry = {'text': '', 'dates': []}
            self.entries.append(self.entry)
        if tag == 'a' and self.groups:
            self.groups[-1]['links'].append(attrs.get('href', ''))
        if tag == 'time' and self.entry is not None:
            self.entry['dates'].append(attrs.get('datetime', ''))
    def handle_data(self, text):
        if self.entry is not None:
            self.entry['text'] += text
    def handle_endtag(self, tag):
        if tag == 'li':
            self.entry = None

def test_bibliography_groups_acts_and_dates_each_real_entry():
    page = Bibliography((SESSION / 'cursus/sources.html').read_text(encoding='utf-8'))
    assert page.groups and page.entries
    for deck in (SESSION / 'cursus').glob('[0-9][0-9]-*.html'):
        assert any(deck.name in group['links'] for group in page.groups), deck
    for entry in page.entries:
        assert entry['text'].strip() and 'Accessed' in entry['text'], entry
        assert entry['dates'], entry
        assert all(date.fromisoformat(d) <= date.today() for d in entry['dates']), entry
