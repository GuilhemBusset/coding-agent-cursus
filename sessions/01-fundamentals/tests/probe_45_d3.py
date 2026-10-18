from html import unescape
from pathlib import Path
import re


def test_both_agents_have_demo_and_submission_commands():
    source = (Path(__file__).resolve().parents[1] / 'exercises/home.html').read_text(encoding='utf-8')
    text = ' '.join(unescape(re.sub('<[^>]+>', '', source)).split())
    assert 'one coding agent, Claude Code or Codex' in text
    for demo_id in ('demo-sampling', 'demo-strawberry'):
        demo = re.search(r'<div class="demo" id="' + demo_id + r'">(.*?)(?=<div class="demo"|<div class="callout good")', source, re.S)[1]
        assert 'Claude Code' in demo and 'claude -p' in demo
        assert 'Codex' in demo and 'codex exec' in demo
    assert 'It is the same for both agents.' in text
    for command in ('/turn-in 01', '$turn-in 01', 'bash scripts/turn-in.sh 01'):
        assert command in text
