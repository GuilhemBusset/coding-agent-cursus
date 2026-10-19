"""Compare the deck's context/cache example to its actual recording."""
from html.parser import HTMLParser
from pathlib import Path
import json


SESSION = Path(__file__).resolve().parents[1]


class Slides(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.current = None
        self.text = {}
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'section' and 'data-slide' in attrs:
            self.current = attrs['id']
            self.text[self.current] = ''

    def handle_endtag(self, tag):
        if tag == 'section':
            self.current = None

    def handle_data(self, data):
        if self.current:
            self.text[self.current] += data


def test_context_and_cache_example_matches_recorded_usage():
    slides = Slides((SESSION / 'cursus/03-agent.html').read_text()).text
    run = json.loads((SESSION / 'cursus/fixtures/runs/context-bomb-claude.json').read_text())
    calls = [s['tokens'] for s in run['steps'] if s.get('tokens') and s['tokens'].get('input') is not None]
    assert calls
    total = sum(c['input'] for c in calls)
    cached = sum(c.get('cached_input') or 0 for c in calls)
    assert total == run['totals']['input']
    assert cached == run['totals']['cached_input']
    assert f"{len(calls)} calls" in slides['resend']
    assert f"{calls[0]['input']:,}" in slides['resend']
    assert f"{calls[-1]['input']:,}" in slides['resend']
    assert f"{max(c['input'] for c in calls):,}" in slides['cost-growth']
    assert f"{total:,}" in slides['cost-growth']
    assert f"{cached:,}" in slides['kv-cache']
    assert f"{round(100 * cached / total)}%" in slides['kv-cache']
    other = json.loads((SESSION / 'cursus/fixtures/runs/context-bomb-codex.json').read_text())
    assert f"{other['totals']['input']:,}" in slides['cost-growth']
