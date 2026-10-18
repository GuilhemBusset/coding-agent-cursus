"""Cross-check the instructor's peer answers with the actual exit ticket (D3)."""
from html.parser import HTMLParser
from pathlib import Path
import re
import unicodedata

SESSION = Path(__file__).resolve().parents[1]


class Text(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.parts = []
        self.feed(source)

    def handle_data(self, data):
        self.parts.append(data)

    def normalized(self):
        text = unicodedata.normalize("NFKD", "".join(self.parts)).lower()
        return " ".join(re.findall(r"[a-z0-9_]+", text))


def test_notes_supply_answers_for_each_act_and_reuse_the_primer():
    raw = (SESSION / "cursus/instructor-notes.html").read_text(encoding="utf-8")
    notes = Text(raw).normalized()
    close = (SESSION / "cursus/99-close.html").read_text(encoding="utf-8")
    labels = dict(re.findall(r'<label for="([^"]+)">(.*?)</label>', close, re.S))
    ids = re.findall(r'<input\b[^>]*id="([^"]+)"[^>]*data-correct', close)
    assert len(ids) == 5
    for ident in ids:
        answer = Text(labels[ident]).normalized()
        # The instructor uses active voice where the ticket uses passive voice.
        if ident == "q3-resend":
            assert re.search(r"re sends? (?:the )?(?:whole )?transcript", notes)
        else:
            assert answer in notes, f"Instructor notes omit the marked answer: {answer}"
    assert "instructor-llm-architecture-primer.md" in raw
    for topic in ("whole sentences", "sampling is random guessing", "moe", "rag",
                  "multi head attention", "why only one layer"):
        assert topic in notes
    for act in range(1, 6):
        assert f'id="act-{act}-misconceptions"' in raw
        assert f'id="act-{act}-questions"' in raw
