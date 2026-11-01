"""The benchmark answer in the instructor notes must not pass off two scores of one model as a gap
between models (the Act III slide that carried it moved there)."""
from html.parser import HTMLParser
from pathlib import Path
import re


class Answer(HTMLParser):
    """The text of the instructor notes' benchmark answer, div#act-3-benchmarks."""

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.text = []

    def handle_starttag(self, tag, attrs):
        if self.depth:
            self.depth += tag == 'div'
        elif tag == 'div' and dict(attrs).get('id') == 'act-3-benchmarks':
            self.depth = 1

    def handle_endtag(self, tag):
        if self.depth and tag == 'div':
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.text.append(data)


def test_the_same_model_pair_is_named_as_such_and_the_gap_is_between_models():
    notes = Path(__file__).resolve().parents[1] / 'cursus/instructor-notes.html'
    parser = Answer()
    parser.feed(notes.read_text(encoding='utf-8'))
    text = ' '.join(' '.join(parser.text).split())
    assert text, 'the instructor notes answer the benchmark question'
    # The vendor's and the leaderboard's figures for each model, as the answer quotes them.
    opus = {'66.4', '64.8'}
    astra = {'57.9', '58.2'}
    assert opus | astra <= set(re.findall(r'\d+\.\d', text))
    pairs = re.findall(r'(\d+\.\d) and (\d+\.\d) are two evaluations of the same model', text)
    assert pairs, 'the answer names the same-model pair'
    for a, b in pairs:
        assert {a, b} <= opus or {a, b} <= astra, f'{a} and {b} are not one model’s two scores'
