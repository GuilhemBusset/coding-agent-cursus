"""Regression for the cache advice, checked against its cited vendor documentation.

https://code.claude.com/docs/en/prompt-caching, read 2026-10-18:
Editing project-root CLAUDE.md mid-session preserves the cache because it is not
reloaded. Changing effort also preserves it on Opus 5.5, Haiku 5.5 and Fable 5.1
with direct API keys or subscriptions. The deck uses these models.
"""
from html.parser import HTMLParser
from pathlib import Path
import re


class CacheAdvice(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_cache = False
        self.in_drive = False
        self.advice = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'section' and attrs.get('id') == 'kv-cache':
            self.in_cache = True
        if self.in_cache and tag == 'p' and 'drive' in attrs.get('class', '').split():
            self.in_drive = True

    def handle_endtag(self, tag):
        if tag == 'section':
            self.in_cache = False
        if tag == 'p':
            self.in_drive = False

    def handle_data(self, data):
        if self.in_cache and self.in_drive:
            self.advice.append(data)


def test_cache_advice_does_not_claim_all_setting_and_instruction_edits_invalidate():
    deck = Path(__file__).resolve().parents[1] / 'cursus/03-agent.html'
    parser = CacheAdvice()
    parser.feed(deck.read_text(encoding='utf-8'))
    text = ' '.join(' '.join(parser.advice).split())
    assert text, 'The cache slide must give usable driving advice'
    blanket = re.search(r'each change throws the memo away', text, re.I)
    assert not blanket, (
        'The advice incorrectly treats every effort change and instruction-file edit '
        'as a cache invalidation; the cited docs describe cache-preserving cases '
        'for the very models in this deck. Qualify or replace this blanket claim.'
    )
