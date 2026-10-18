"""Independent A1 witness: fresh checks beside dated teaching claims."""
from datetime import date
from html import unescape
from pathlib import Path
import re

SESSION = Path(__file__).resolve().parents[1]

def visible(raw):
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]*>', ' ', raw))).strip()

def test_teaching_claim_dates_have_a_current_check():
    sources = (SESSION / 'cursus/sources.html').read_text(encoding='utf-8')
    checked = date.fromisoformat(re.search(r'data-fact-check="([0-9-]+)"', sources)[1])
    assert checked <= date.today()
    stale = []
    for page in [*(SESSION / 'cursus').rglob('*.html'), *(SESSION / 'exercises').rglob('*.html')]:
        raw = page.read_text(encoding='utf-8')
        raw = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', raw, flags=re.S | re.I)
        # A table's caption may qualify a frozen snapshot in its date column.
        blocks = re.findall(r'<table\b[^>]*>(.*?)</table>', raw, re.S | re.I)
        raw = re.sub(r'<table\b[^>]*>.*?</table>', '', raw, flags=re.S | re.I)
        blocks += re.findall(r'<(?:p|figcaption|footer)\b[^>]*>(.*?)</(?:p|figcaption|footer)>', raw, re.S | re.I)
        for block in blocks:
            text = visible(block)
            dates = re.findall(r'\b(?:as of|checked|read|accessed)\b[^.;]{0,80}?(\d{4}-\d{2}-\d{2})', text, re.I)
            rechecks = re.findall(r'\brechecked\b[^.;]{0,80}?(\d{4}-\d{2}-\d{2})', text, re.I)
            if dates and max(dates + rechecks) < checked.isoformat():
                stale.append((str(page.relative_to(SESSION)), text))
    assert not stale, stale
