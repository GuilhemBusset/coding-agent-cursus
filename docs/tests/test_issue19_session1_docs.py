"""Issue #19 acceptance evidence, scoped to the approved Session 1 rescope.

Run with: uv run --project sessions/01-fundamentals pytest \
    docs/tests/test_issue19_session1_docs.py -q

A2 pins base commit 4f2cd35. A later issue legitimately changing Sessions 2–5
should delete or update that test. Schedule and demo expectations come from
tools/implementation-loop/tests/fixtures/epic10.json, issues #10 and #12–#17
(especially #16 for the lab ladder), not from the inaccessible artifact URL.
These offline checks establish structural/content evidence; the independent
reviewer still judges teaching quality, explanation, voice, and plan fidelity.
Only standard-library imports are needed in this pytest module.
"""

from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
NARRATIVE = "docs/cursus-narrative.md"
NOTIONS = "docs/cursus-key-technical-notions.md"
BASE = "4f2cd35"
PARTS = (
    ("Opening", "0:00", "0:15"),
    ("Act I: The sampler", "0:15", "1:00"),
    ("Act II: Thinking", "1:10", "1:55"),
    ("Act III: Agent = model + harness", "1:55", "2:35"),
    ("Act IV: Drive it yourself", "2:45", "3:35"),
    ("Act V: When agents fail", "3:35", "3:55"),
    ("Close", "3:55", "4:00"),
)


def read(path):
    return (ROOT / path).read_bytes().decode("utf-8")


def section(text):
    match = re.search(r"^## Session 1 — Fundamentals\s*\n(.*?)^## Session 2\b",
                      text, re.M | re.S)
    assert match, "Expected Session 1 — Fundamentals followed by Session 2"
    return match.group(1)


def preamble():
    return read(NARRATIVE).split("## Session 1", 1)[0]


def plain(text):
    return re.sub(r"\s+", " ", text.replace("*", "").replace("`", "")).strip()


def paragraphs(text):
    return [plain(p) for p in re.split(r"\n\s*\n", text) if p.strip()]


def sentences(text):
    # Split prose punctuation, not decimals, filenames, or dots inside URLs.
    return [s for p in paragraphs(text)
            for s in re.split(r"(?<=[.!?])\s+", p) if s]


def require(text, *terms):
    folded = plain(text).casefold()
    for term in terms:
        assert term.casefold() in folded, f"Missing {term!r} in: {text}"


def has_any(text, terms):
    return any(term.casefold() in text.casefold() for term in terms)


def interval(start, end):
    return re.escape(start) + r"\s*(?:[–-]|to)\s*" + re.escape(end)


def blocks():
    text = section(read(NARRATIVE))
    matches = []
    for name, start, end in PARTS:
        pattern = (r"^\*\*" + re.escape(name) + r" \(" + interval(start, end)
                   + r"\)\.\*\*")
        found = list(re.finditer(pattern, text, re.M | re.I))
        assert len(found) == 1, f"Expected one bold lead-in: {name} ({start}–{end})."
        matches.append(found[0])
    assert [m.start() for m in matches] == sorted(m.start() for m in matches), \
        "Opening, Acts I–V, Close must be in plan order"
    result = {"framing": text[:matches[0].start()]}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        result[PARTS[index][0]] = text[match.end():end].strip()
    return result


def bullets():
    return [plain(m.group(1)).casefold() for m in re.finditer(
        r"^[-*] (.*?)(?=^[-*] |\Z)", section(read(NOTIONS)), re.M | re.S)]


def bullet_with(items, *terms):
    found = [b for b in items if all(t.casefold() in b for t in terms)]
    assert found, f"Expected one bullet explaining {terms}"
    return found[0]


def test_d1_instructor_framing_anchors_and_cross_references():
    text = section(read(NARRATIVE))
    parts = blocks()
    assert len(re.findall(r"\b(?:I\s|I['’]|my\s)", text)) >= 5, "Use instructor voice"
    assert re.search(r"\byou\b", text, re.I), "Address the student"
    assert not re.search(r"^\s*\|", text, re.M), "Narrative should be prose, not a table"
    require(parts["framing"], "does this change how you drive an agent next week",
            "p(x_t", "sub-word", "pure function of its context", "illusion", "harness")
    assert any(all(t in s.casefold() for t in
                   ("backprop", "gradient descent", "transformer block internals", "rlhf"))
               and has_any(s, ("cut", "refuse", "no "))
               for s in sentences(parts["framing"])), "Put the revised cuts in the framing"
    opening = parts["Opening"]
    require(opening, "pre-work", "uv", "mise", "pytest", "Claude Code or Codex",
            "never raise an agent's autonomy past your ability to verify the solution, not just the code")
    harness = parts["Act III: Agent = model + harness"]
    require(harness, "subagent", "context window", "finite", "buffer")
    assert any("subagent" in p.casefold() and "context window" in p.casefold()
               and has_any(p, ("own", "separate", "independent"))
               for p in paragraphs(harness)), "Explain separate subagent context windows"
    lab_and_failure = parts["Act IV: Drive it yourself"] + "\n\n" + parts["Act V: When agents fail"]
    require(lab_and_failure, "solve contract", "status", "whitelist", "independent",
            "re-check", "integrality", "objective", "tolerance", "wrong", "slow",
            "hard red", "feasibility", "invariant", "gap", "Optimal")
    assert has_any(lab_and_failure, ("time-limit", "time limit"))


def test_d2_system1_system2_and_distinct_loops():
    parts = blocks()
    assert any(all(t in p.casefold() for t in ("system 1", "forward pass", "distribution", "fixed"))
               for p in paragraphs(section(read(NARRATIVE)))), "Explain fixed-compute System 1"
    thinking = parts["Act II: Thinking"]
    assert any(all(t in p.casefold() for t in ("system 2", "serial compute"))
               and has_any(p, ("fed back", "feeds", "append"))
               for p in paragraphs(thinking)), "Explain the feedback loop buying serial compute"
    transition = paragraphs(parts["Act I: The sampler"])[-1] + paragraphs(thinking)[0]
    require(transition, "System 1")
    require(thinking, "autoregressive", "same network", "anytime", "verifier")
    items = bullets()
    bullet_with(items, "System 1", "System 2", "forward pass")
    assert not any("chatbot" in b and "single forward pass" in b for b in items)
    loop = bullet_with(items, "token", "tool", "loop")
    require(loop, "chatbot", "agent", "forward pass")
    assert has_any(loop, ("many", "multiple")), "Every reply takes multiple forward passes"


def test_d3_four_hour_arc():
    intro = preamble()
    assert not re.search(r"five sessions of (?:roughly |about )?two hours", intro, re.I)
    assert any("session 1" in s.casefold() and re.search(r"(?:four|4)[- ]hours?", s, re.I)
               for s in sentences(intro)), "State Session 1's four-hour duration"
    subtitle = read(NARRATIVE).splitlines()[2]
    require(subtitle, "Session 1", "interactive")
    assert re.search(r"sessions 2\s*[–-]\s*5.*(?:roughly|about) two hours", subtitle, re.I)
    assert any("re-baselining" in s and re.search(r"(?:four|4)[- ]hours?", s, re.I)
               for s in sentences(intro)), "Explain the four-hour re-baselining"
    assert "two hours" not in section(read(NARRATIVE)).casefold()


def test_d4_homework_and_either_agent():
    text = section(read(NARRATIVE))
    assert "first pull request" not in text.casefold()
    close = blocks()["Close"]
    # /ship may still illustrate reliability controls in Act V, but is no longer homework.
    assert "/ship" not in close
    for literal in ("P01", "/turn-in", "$turn-in", "homework/s01/<handle>",
                    "Claude Code or Codex", "not necessarily both"):
        assert literal in close, f"Close must contain literal {literal!r}"
    assert has_any(plain(close), ("never to main", "not to main"))
    require(close, "either", "instruction", "all term")
    assert "the Claude Code and Codex CLIs" not in preamble()
    require(preamble(), "Claude Code or Codex CLI", "you need one, not both")


def test_d5_key_notions_explain_each_addition():
    items = bullets()
    compute = bullet_with(items, "test-time compute", "effort")
    require(compute, "parallel", "sequential")
    assert has_any(compute, ("overthink", "not always better"))
    bullet_with(items, "verifiable rewards", "one slide")
    assert any(has_any(b, ("chain-of-thought", "chain of thought")) and "faithful" in b
               for b in items), "Explain chain-of-thought faithfulness"
    world = bullet_with(items, "world model", "three", "representation", "simulator")
    assert has_any(world, ("stale", "repo"))
    gap = bullet_with(items, "generator-verifier gap")
    assert has_any(gap, ("certificate", "bound"))
    harness = bullet_with(items, "harness primitives")
    assert sum(t in harness for t in ("agents.md", "skill", "mcp", "subagent", "hook",
                                     "permission", "plan mode", "headless")) >= 5
    gallery = bullet_with(items, "failure gallery")
    assert sum(has_any(gallery, group) for group in (
        ("edited tests", "reward hacking"), ("verifier",), ("prompt injection",),
        ("hallucinated package",), ("secret",), ("sycophancy",))) >= 4
    bullet_with(items, "2026", "landscape")


def test_d6_cuts_and_benchmark_distrust_everywhere():
    cut_terms = ("backprop", "gradient descent", "training loss", "transformer block internals",
                 "rlhf", "scaling laws")
    forbidden = (r"reward model", r"\bPPO\b", r"proximal policy", r"\bDPO\b",
                 r"preference pair", r"Bradley", r"residual stream", r"layer norm",
                 r"feed[- ]forward", r"\bMLP layer")
    for path in (NARRATIVE, NOTIONS):
        text = section(read(path))
        prose = sentences(text)
        cuts = [s for s in prose if all(t in s.casefold() for t in cut_terms)]
        assert len(cuts) == 1, f"{path}: use one complete cut-list sentence"
        assert has_any(cuts[0], ("cut", "refuse", "no "))
        for sentence in prose:
            if any(t in sentence.casefold() for t in cut_terms):
                assert sentence == cuts[0], f"{path}: cut material outside cut list: {sentence}"
            if re.search(r"benchmark|SWE-bench|MMLU|GPQA|HumanEval", sentence, re.I):
                assert has_any(sentence, ("vendor", "standardized", "distrust", "METR",
                                          "time horizon", "time-horizon")), \
                    f"{path}: benchmark claim without distrust/trend framing: {sentence}"
        for pattern in forbidden:
            assert not re.search(pattern, text, re.I), f"{path}: excluded mechanics: {pattern}"
        require(text, "vendor", "standardized", "METR")
        assert has_any(text, ("time horizon", "time-horizon"))
        for paragraph in paragraphs(text):
            if "latest" in paragraph.casefold() or (
                    "2026" in paragraph and "landscape" in paragraph.casefold()):
                assert re.search(r"as[- ]of\s+.{0,40}20\d\d", paragraph, re.I), \
                    f"{path}: date the landscape/latest claim: {paragraph}"
    assert any("metr" in p.casefold() and has_any(p, ("time horizon", "time-horizon"))
               and re.search(r"https?://(?:[\w-]+\.)*metr\.org(?:[/)#?\s]|$)", p)
               and re.search(r"20\d\d", p)
               for p in paragraphs(section(read(NARRATIVE)))), "Date and source METR's trend"


def test_a1_schedule_demos_lab_ladder_and_close():
    parts = blocks()  # Also verifies all seven ordered names and exact time intervals.
    for names, start, end in (
        (("Act I: The sampler", "Act II: Thinking"), "1:00", "1:10"),
        (("Act III: Agent = model + harness", "Act IV: Drive it yourself"), "2:35", "2:45"),
    ):
        assert any("break" in s.casefold() and re.search(interval(start, end), s)
                   for name in names for s in sentences(parts[name])), f"Missing break {start}–{end}"
    require(parts["Opening"], "cold open", "HiGHS", "certif", "METR", "poll")
    require(parts["Act I: The sampler"], "strawberry", "code")
    thinking = parts["Act II: Thinking"]
    require(thinking, "effort")
    assert has_any(thinking, ("dial", "low and high"))
    require(parts["Act III: Agent = model + harness"], "flipped objective", "context bomb",
            "Claude Code", "Codex")
    require(parts["Act V: When agents fail"], "catch the agent", "three diffs", "one honest fix")
    lab = parts["Act IV: Drive it yourself"]
    require(lab, "P00")
    levels = list(re.finditer(r"\bL[1-4]\b", lab))
    # Bind each requirement to its own rung; an unrelated keyword list cannot pass.
    first = []
    for level in range(1, 5):
        found = [m for m in levels if m.group() == f"L{level}"]
        assert found, f"Missing lab level L{level}"
        first.append(found[0])
    assert [m.start() for m in first] == sorted(m.start() for m in first)
    ladder = [lab[m.end():first[i + 1].start() if i < 3 else len(lab)]
              for i, m in enumerate(first)]
    require(ladder[0], "explore", "read-only", "predict")
    require(ladder[1], "verifier", "git diff --stat -- tests/", "empty", "green", "protect")
    require(ladder[2], "certificate", "plan mode", "independent checker", "bound")
    require(ladder[3], "stretch", "AGENTS.md", "skill", "headless", "claude -p", "codex exec")
    require(parts["Close"], "exit ticket", "five", "predict-and-reveal", "one per act",
            "two demos", "three sentences", "sampling, not retrieval", "P01", "EV linehaul",
            "charging", "/turn-in", "Session 2")


def test_a2_later_sessions_match_pinned_base_with_only_required_substitution():
    marker = b"## Session 2"
    old = "one coding agent — Claude Code, on your own laptop".encode()
    new = "one coding agent — Claude Code or Codex, on your own laptop".encode()
    for path in (NARRATIVE, NOTIONS):
        result = subprocess.run(["git", "show", f"{BASE}:{path}"], cwd=ROOT,
                                capture_output=True, check=False)
        assert result.returncode == 0, f"Pinned base {BASE} is required: {result.stderr!r}"
        current = (ROOT / path).read_bytes()
        assert marker in result.stdout and marker in current
        expected = result.stdout[result.stdout.index(marker):]
        if path == NARRATIVE:
            assert expected.count(old) == 1, "Base must contain exactly one authorized edit target"
            expected = expected.replace(old, new, 1)
        assert current[current.index(marker):] == expected, \
            f"{path}: Sessions 2–5 and all following content must match {BASE} (plus authorized edit)"


def test_a3_no_prior_agent_experience_assumed():
    assert "I assume no prior experience driving a coding agent" in preamble()
