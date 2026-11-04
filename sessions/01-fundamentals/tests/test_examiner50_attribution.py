"""Independent A2 witness for the identified single-secondary incident quotes.

The PocketOS case moved from the old Act V deck to Act IV's #l1 slide, where it is the failure L1
guards against. Its founder's words are known only through Tom's Hardware, so wherever the slide
and its notes quote them, they say so, link the founder's own article and Railway's account.
"""
import re
from html import unescape
from pathlib import Path

SESSION = Path(__file__).resolve().parents[1]


def test_pocketos_quotes_are_attributed_and_primary_account_is_linked():
    raw = (SESSION / 'cursus/04-evidence.html').read_text(encoding='utf-8')
    match = re.search(r'<section\b[^>]*id="l1"[^>]*>(.*?)</section>', raw, re.S)
    assert match, 'Act IV #l1 carries the PocketOS case'
    section = match[1]
    assert 'https://blog.railway.com/p/your-ai-wants-to-nuke-your-database' in section
    assert 'https://x.com/lifeofjer/status/2048103471019434248' in section
    text = unescape(re.sub(r'<[^>]*>', ' ', section))
    assert re.search(r'founder.*?as quoted by Tom', text, re.S | re.I), text
    if '9 seconds' in text:
        assert re.search(r'founder, as quoted.*?9 seconds', text, re.S | re.I), text
    assert re.search(r'without naming the customer', text, re.I), text
    # Railway recovered the database: nothing on the slide may say the data was lost for good.
    assert re.search(r'recovered', text, re.I), text
