from html import unescape
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


def test_homework_has_four_actionable_parts_and_local_materials():
    session = Path(__file__).resolve().parents[1]
    page = session / 'exercises/home.html'
    source = page.read_text(encoding='utf-8')
    sections = dict(re.findall(r'<section id="([^"]+)"[^>]*>(.*?)</section>', source, re.S))
    text = {key: ' '.join(unescape(re.sub('<[^>]+>', ' ', body)).split()) for key, body in sections.items()}
    assert all(f'part-{i}' in text for i in range(1, 5))
    assert 'two' in text['part-1'].lower() and 'what changed' in text['part-1'].lower()
    assert 'exactly three sentences' in text['part-2'] and 'sampling, not retrieval' in text['part-2']
    assert 'your own agent' in text['part-3'] and 'p01_model.py' in text['part-3']
    assert '/turn-in 01' in text['part-4'] and '$turn-in 01' in text['part-4']
    for href in re.findall(r'href="([^"]+)"', source):
        url = urlsplit(unescape(href))
        if not url.scheme and url.path:
            target = (page.parent / unquote(url.path)).resolve()
            assert target.is_relative_to(session) and target.exists(), href
