"""Both harnesses expose the same explicit-only thin wrapper."""

import re

from test_ci_checks import run_step, workflow_steps
from test_turn_in_script import ROOT, write


AGENT = ".agents/skills/turn-in/SKILL.md"
CLAUDE = ".claude/skills/turn-in/SKILL.md"


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.S)
    assert match, f"Missing skill frontmatter in {path}"
    fields = dict(re.findall(r"(?m)^([\w-]+):\s*(.+)$", match.group(1)))
    return fields, text[match.end():]


def test_regular_identical_skill_files_and_explicit_flags():
    for relative in (AGENT, CLAUDE):
        path = ROOT / relative
        assert path.is_file() and not path.is_symlink(), f"Missing regular skill file: {relative}"
    assert (ROOT / AGENT).read_bytes() == (ROOT / CLAUDE).read_bytes()
    fields, body = frontmatter(ROOT / AGENT)
    ship, _ = frontmatter(ROOT / ".agents/skills/ship/SKILL.md")
    assert fields.get("name") == "turn-in"
    for flag in ("disable-model-invocation", "allowed-tools", "compatibility"):
        assert fields.get(flag) == ship[flag], f"{flag} must match ship"
    assert fields["disable-model-invocation"] == "true"
    description = fields.get("description", "")
    assert "explicit" in description.lower() and "do not invoke implicitly" in description.lower()
    for token in ("/turn-in", "$turn-in"):
        assert token in description
        assert token in body
    assert "scripts/turn-in.sh" in body
    assert "$ARGUMENTS" not in body
    assert re.search(r"\b(ask|request)\b", body, re.I) and re.search(r"\b(missing|absent|omitted|not provided)\b", body, re.I)


def test_codex_disallows_implicit_invocation_under_policy():
    text = (ROOT / ".agents/skills/turn-in/agents/openai.yaml").read_text()
    # Ignore comments; top-level allow_implicit_invocation does not work in Codex.
    text = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    policy = re.search(r"(?m)^policy:\s*\n((?:[ \t]+[^\n]*(?:\n|$)|\s*\n)+)", text)
    assert policy, "openai.yaml needs a policy mapping"
    assert re.search(r"(?m)^\s+allow_implicit_invocation:\s*false\s*$", policy.group(1))
    assert not re.search(r"(?m)^allow_implicit_invocation:", text)


def test_workflow_diff_is_live_and_detects_drift(tmp_path):
    expected = f"diff -u {AGENT} {CLAUDE}"
    candidates = [s for s in workflow_steps() if s["run"] and expected in s["run"]]
    assert len(candidates) == 1, "Add the turn-in byte-identity diff step"
    script = candidates[0]["run"]
    run_step(script, ROOT)
    for relative in (AGENT, CLAUDE):
        write(tmp_path / relative, (ROOT / relative).read_text())
    run_step(script, tmp_path)
    with (tmp_path / CLAUDE).open("a") as stream:
        stream.write("\nDrift introduced by the acceptance test.\n")
    assert run_step(script, tmp_path, ok=False).returncode != 0
