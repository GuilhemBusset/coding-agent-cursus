"""Check that the numerical example in the talk track matches its table."""
from html.parser import HTMLParser
from pathlib import Path
import re


class BenchmarkSlide(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.row = None
        self.rows = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == 'section' and dict(attrs).get('id') == 'benchmarks':
            self.active = True
        if self.active and tag == 'tr':
            self.row = []

    def handle_endtag(self, tag):
        if self.active and tag == 'tr':
            self.rows.append(' '.join(self.row))
            self.row = None
        if tag == 'section':
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.text.append(data)
            if self.row is not None:
                self.row.append(data)


def test_between_model_example_does_not_compare_two_scores_for_the_same_model():
    deck = Path(__file__).resolve().parents[1] / 'cursus/03-agent.html'
    parser = BenchmarkSlide()
    parser.feed(deck.read_text(encoding='utf-8'))
    rows = [set(re.findall(r'(\d+(?:\.\d+)?)%', row)) for row in parser.rows]
    assert any(len(row) >= 2 for row in rows), 'Benchmark slide needs its comparison table'
    text = ' '.join(parser.text)
    for a, b in re.findall(r'between models:\s*(\d+(?:\.\d+)?)\s+versus\s+(\d+(?:\.\d+)?)', text):
        assert not any({a, b} <= row for row in rows), (
            f'{a} versus {b} comes from the same model row, comparing vendor and '
            'leaderboard evaluations; it is not a difference between models.'
        )
