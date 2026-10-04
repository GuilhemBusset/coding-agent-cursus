"""The instructor-settled automated documentation proof (D5).

D6 disclosure confirmation and A1 live GitHub/agent probes are manual evidence;
these assertions deliberately do not purport to close those ledger items.
"""

import re

import pytest

from test_turn_in_script import ROOT


@pytest.mark.parametrize("filename", ["AGENTS.md", "README.md"])
def test_turning_in_homework_section(filename):
    source = (ROOT / filename).read_text(encoding="utf-8")
    heading = re.search(r"(?m)^(#{1,6})[ \t]+Turning in homework[ \t]*#*[ \t]*$", source)
    assert heading, f"{filename} needs a Turning in homework heading"
    rest = source[heading.end():]
    next_heading = re.search(r"(?m)^#{1," + str(len(heading.group(1))) + r"}\s+", rest)
    section = rest[:next_heading.start()] if next_heading else rest
    assert "/turn-in" in section and "$turn-in" in section
    assert re.search(r"\bpublic\b", section, re.I), "The homework section must disclose public visibility"


def test_homework_adr_has_a_unique_number_and_cites_ship_decision():
    folder = ROOT / "docs/adr"
    matches = list(folder.glob("[0-9][0-9][0-9][0-9]-homework-on-per-student-branches.md"))
    assert len(matches) == 1, "Exactly one numbered homework branch ADR is required"
    adr = matches[0]
    assert len(list(folder.glob(adr.name[:4] + "-*.md"))) == 1, "ADR number already taken"
    assert "0003" in adr.read_text(encoding="utf-8"), "Cite ADR 0003's shared ship pattern"
