"""Compare the deck's token pictures to the recordings they draw.

#resend draws Act III's opening run, three model calls, from Claude Code's own usage blocks (cache read,
cache write, uncached); #long-run prices the 26 calls of the long task and shows the CLI's own bill.
"""
import json
from html.parser import HTMLParser
from pathlib import Path

SESSION = Path(__file__).resolve().parents[2]
RUNS = SESSION / 'cursus/fixtures/runs'


class Slides(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.current = None
        self.depth = 0
        self.text = {}
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'section' and 'data-slide' in attrs:
            self.current, self.depth = attrs['id'], 0
            self.text[self.current] = ''
        elif tag == 'section' and self.current:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == 'section' and self.current:
            if self.depth == 0:
                self.current = None
            else:
                self.depth -= 1

    def handle_data(self, data):
        if self.current:
            self.text[self.current] += data


def usage_per_call(raw):
    """One usage block per model call: the stream repeats it on every event of the same message id."""
    calls = {}
    for line in raw.read_text(encoding='utf-8').splitlines():
        event = json.loads(line)
        if event.get('type') == 'assistant':
            message = event['message']
            calls.setdefault(message['id'], message['usage'])
    return list(calls.values())


def test_resend_draws_the_three_calls_of_act_two_run():
    slides = Slides((SESSION / 'cursus/03-agent.html').read_text(encoding='utf-8')).text
    run = json.loads((RUNS / 'flipped-sense-claude.json').read_text(encoding='utf-8'))
    calls = usage_per_call(RUNS / 'raw/flipped-sense-claude.jsonl')
    assert len(calls) == 3
    totals = [c['cache_read_input_tokens'] + c['cache_creation_input_tokens'] + c['input_tokens'] for c in calls]
    assert sum(totals) == run['totals']['input']
    text = slides['resend']
    for call, total in zip(calls, totals):
        assert f"{total:,}" in text, total
        assert f"{call['cache_read_input_tokens']:,}" in text
        assert f"{call['cache_creation_input_tokens']:,}" in text
    # Each call re-sends the previous one: its cache read is the previous call's input, give or take
    # the uncached tail.
    for before, after in zip(totals, calls[1:]):
        assert abs(after['cache_read_input_tokens'] - before) <= 2


def test_long_run_prices_every_call_of_the_long_task_and_shows_the_cli_bill():
    slides = Slides((SESSION / 'cursus/03-agent.html').read_text(encoding='utf-8')).text
    run = json.loads((RUNS / 'context-bomb-claude.json').read_text(encoding='utf-8'))
    raw = RUNS / 'raw/context-bomb-claude.jsonl'
    calls = usage_per_call(raw)
    assert len(calls) == 26
    sent = [c['cache_read_input_tokens'] + c['cache_creation_input_tokens'] + c['input_tokens'] for c in calls]
    # The normalized replay and the raw usage blocks agree on what each call sent.
    replay = [s['tokens']['input'] for s in run['steps'] if s.get('tokens') and s['tokens'].get('input') is not None]
    assert sent == replay
    result = next(e for e in map(json.loads, raw.read_text(encoding='utf-8').splitlines()) if e.get('type') == 'result')
    text = slides['long-run']
    for n in sent:
        assert f"{n:,} tokens sent" in text, n
    assert f"${result['total_cost_usd']:.2f}" in text
    assert f"{round(sent[-1] / sent[0])}× the tokens" in text
