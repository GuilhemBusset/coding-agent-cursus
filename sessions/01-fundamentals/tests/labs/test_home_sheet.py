"""The Session 1 homework sheet asks students to rerun the demos with the prompts run in class."""

import ast
import re
from html import unescape
from pathlib import Path

SESSION = Path(__file__).resolve().parents[2]
SHEET = SESSION / "exercises" / "home.html"


def script_constants(path, *names):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values = {t.id: node.value for node in tree.body if isinstance(node, ast.Assign) for t in node.targets}
    return [ast.literal_eval(values[name]) for name in names]


def test_demo_prompts_are_the_ones_run_in_class():
    source = unescape(SHEET.read_text(encoding="utf-8"))
    demos = SESSION / "cursus" / "demos" / "model"
    (sampling,) = script_constants(demos / "sampling.py", "PROMPT")
    word, ask = script_constants(demos / "strawberry.py", "WORD", "ASK")
    assert source.count(f'"{sampling}"') == 2  # once per agent
    prompt = re.search(r'aria-label="Strawberry prompt"><code>(.*?)</code>', source, re.DOTALL)
    assert prompt and prompt.group(1) == ask.format(WORD=word)
