"""Independent A2 witness for the identified single-secondary incident quotes."""
from html import unescape
from pathlib import Path
import re

SESSION = Path(__file__).resolve().parents[1]

def test_pocketos_quotes_are_attributed_and_primary_account_is_linked():
    raw = (SESSION / 'cursus/05-failure.html').read_text(encoding='utf-8')
    match = re.search(r'<section\b[^>]*id="pocketos"[^>]*>(.*?)</section>', raw, re.S)
    if not match:
        return  # Removing the secondary-only incident is allowed by the issue.
    section = match[1]
    assert 'https://blog.railway.com/p/your-ai-wants-to-nuke-your-database' in section
    assert 'https://x.com/lifeofjer/status/2048103471019434248' in section
    text = unescape(re.sub(r'<[^>]*>', ' ', section))
    assert re.search(r'founder.*?as quoted by Tom', text, re.S | re.I), text
    if '9 seconds' in text:
        assert re.search(r'founder, as quoted.*?9 seconds', text, re.S | re.I), text
    assert re.search(r'without naming the customer', text, re.I), text
