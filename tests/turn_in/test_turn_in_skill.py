"""Turning in pushes public homework, so neither harness may run the skill on its own."""

import re

from test_turn_in_script import ROOT


def test_the_skill_frontmatter_forbids_implicit_invocation():
    for skill in (".claude/skills/turn-in/SKILL.md", ".agents/skills/turn-in/SKILL.md"):
        text = (ROOT / skill).read_text(encoding="utf-8")
        frontmatter = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        assert frontmatter, f"Missing skill frontmatter in {skill}"
        assert re.search(r"(?m)^disable-model-invocation:\s*true\s*$", frontmatter.group(1)), skill


def test_codex_never_invokes_the_skill_on_its_own():
    text = (ROOT / ".agents/skills/turn-in/agents/openai.yaml").read_text()
    # Ignore comments; top-level allow_implicit_invocation does not work in Codex.
    text = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    policy = re.search(r"(?m)^policy:\s*\n((?:[ \t]+[^\n]*(?:\n|$)|\s*\n)+)", text)
    assert policy, "openai.yaml needs a policy mapping"
    assert re.search(r"(?m)^\s+allow_implicit_invocation:\s*false\s*$", policy.group(1))
