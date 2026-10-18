"""Independent pre-reading contract for issue 24."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


class Reading(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.active = False
        self.links = []
        self.text = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'section':
            self.active = attrs.get('id') == 'reading'
        if self.active and tag == 'a':
            self.links.append(attrs.get('href', ''))

    def handle_endtag(self, tag):
        if tag == 'section':
            self.active = False

    def handle_data(self, text):
        if self.active:
            self.text.append(text)


def test_D4_readings_and_selected_chapters():
    root = Path(__file__).resolve().parents[1]
    reading = Reading((root / 'sessions/01-fundamentals/exercises/00-prework.html').read_text())
    text = ' '.join(reading.text)
    for name in ('3Blue1Brown', 'explained briefly', 'Karpathy', 'How I use LLMs',
                 'Claude Code 101', 'Get Started with Codex'):
        assert name in text, name
    videos = [parse_qs(urlsplit(link).query) for link in reading.links
              if urlsplit(link).hostname == 'www.youtube.com']
    assert any(query.get('v') == ['LPZh9BOjkQs'] for query in videos)
    chapters = [query['t'][0] for query in videos
                if query.get('v') == ['EWvNQjAaOHw'] and 't' in query]
    assert len(set(chapters)) >= 2, 'Karpathy reading must select chapters'
    assert all(int(timestamp.rstrip('s')) > 0 for timestamp in chapters)
    assert 'https://anthropic.skilljar.com/claude-code-101' in reading.links
    assert any(urlsplit(link).hostname == 'academy.openai.com'
               and 'codex' in urlsplit(link).path for link in reading.links)
