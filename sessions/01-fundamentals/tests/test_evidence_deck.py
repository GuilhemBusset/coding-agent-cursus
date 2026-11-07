"""Act IV's #check slide, checked against what the mini homework's check.py really prints.

The three rosters and their claims are the deck's own, illustrative. Each card shows the roster, the headcount it
claims, and check.py's output for that file: the lines shown are check.py's, verbatim, in its order, and the closing
"… +N contract" line counts exactly the lines left out. No card passes, which is the slide's predict. HiGHS's
Optimal on the LP relaxation (card A) is checked in test_mini_homework.py.
"""
import html
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

SESSION = Path(__file__).resolve().parents[1]
DECK = SESSION / "cursus/04-evidence.html"
CHECK = SESSION / "exercises/mini-homework/check.py"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def cards():
    section = re.search(r'<section id="check".*?</section>', DECK.read_text(encoding="utf-8"), re.S)
    assert section, "Act IV has a #check slide"
    found = {}
    for key, body in re.findall(r'<div class="ck-card" data-ck="(\w)">(.*?)<span class="rp-q-mark', section[0], re.S):
        text = lambda cls: html.unescape(re.sub(r"<[^>]+>", "", re.search(rf'class="{cls}"[^>]*>(.*?)</(?:p|pre)>', body, re.S)[1]))
        claim = float(re.search(r"(\d+(?:\.\d+)?) people", text("ck-claim"))[1])
        roster = [float(value) for value in text("ck-roster").split()[1:]]
        found[key] = claim, roster, text("rp-ans").splitlines()
    assert sorted(found) == ["A", "B", "C"], found
    return found


def check(tmp_path, claim, roster):
    solution = tmp_path / "solution.json"
    solution.write_text(json.dumps({"objective": claim, "start": dict(zip(DAYS, roster))}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(CHECK), str(solution)], capture_output=True, text=True,
                            encoding="utf-8", timeout=10, check=False)
    return result.returncode, result.stdout.split("\n\n")[0].splitlines()


@pytest.mark.parametrize("key", ["A", "B", "C"])
def test_check_cards_show_check_py_output_and_count_what_they_leave_out(key, tmp_path):
    claim, roster, shown = cards()[key]
    assert len(roster) == 7, roster
    code, real = check(tmp_path, claim, roster)
    assert code == 1 and real[0] == "FAIL", "no card passes: the predict's answer is none"
    *lines, rest = shown
    assert lines[0] == "FAIL" and rest.startswith("…"), shown
    assert lines[1:] == [line for line in real[1:] if line in lines[1:]], "the lines shown are check.py's, in its order"
    left_out = Counter(line.split(":")[0] for line in real[1:] if line not in lines)
    counted = Counter({contract: int(n) for n, contract in re.findall(r"\+(\d+) (\w+)", rest)})
    assert left_out == counted, f"{rest!r} counts the lines left out: {dict(left_out)}"
    for day in re.findall(r"\((.*?)\)", rest)[0].split(", ") if "(" in rest else []:
        assert any(day in line for line in real if line not in lines), f"{day} is among the lines left out"
