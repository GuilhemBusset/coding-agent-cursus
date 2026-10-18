from html import unescape
from pathlib import Path
import re


def test_each_part_explains_quality_and_feasibility_precedes_objective():
    source = (Path(__file__).resolve().parents[1] / 'exercises/home.html').read_text(encoding='utf-8')
    parts = re.findall(r'<section id="part-[1-4]"[^>]*>(.*?)</section>', source, re.S)
    assert len(parts) == 4
    for part in parts:
        good = re.search(r'<div class="callout good">(.*?)</div>', part, re.S)
        assert good and 'What a good answer looks like' in good[1]
        assert len(re.findall(r'<li>', good[1])) >= 2
    text = ' '.join(unescape(re.sub('<[^>]+>', ' ', source)).split()).lower()
    assert 'feasibility proven by the checker counts more than the objective value' in text
    assert 'only optimality fails' in text
    assert 'every feasibility contract passes' in text
    assert 'a plan the model does not produce' in text
