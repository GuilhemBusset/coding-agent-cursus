"""Exercise the run-of-show's actual fallback commands and time coverage (D2)."""
from html.parser import HTMLParser
from pathlib import Path
import os
import re
import shlex
import subprocess

SESSION = Path(__file__).resolve().parents[1]


class Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell, self.code = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag == "td":
            self.cell = {"text": "", "codes": []}
        elif tag == "code" and self.cell is not None:
            self.code = ""

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"] += data
        if self.code is not None:
            self.code += data

    def handle_endtag(self, tag):
        if tag == "code" and self.code is not None:
            self.cell["codes"].append(self.code)
            self.code = None
        elif tag == "td" and self.cell is not None:
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = None


def test_run_of_show_has_no_time_gaps_and_its_fallbacks_work():
    source = (SESSION / "cursus/run-of-show.html").read_text(encoding="utf-8")
    parser = Rows()
    parser.feed(source)
    rows = [r for r in parser.rows if len(r) == 7]
    spans = [r[0]["text"] for r in rows]
    spans += re.findall(r'<h2 id="break-[^"]+">(\d+:\d+–\d+:\d+)', source)
    def seconds(time):
        parts = list(map(int, time.split(":")))
        return parts[0] * 3600 + parts[1] * 60 + (parts[2] if len(parts) == 3 else 0)
    intervals = sorted(tuple(seconds(t) for t in span.split("–")) for span in spans)
    assert intervals[0][0] == 0 and intervals[-1][1] == 4 * 3600
    assert all(a < b for a, b in intervals)
    assert all(a[1] == b[0] for a, b in zip(intervals, intervals[1:]))
    commands_run = 0
    for row in rows:
        assert any(mode in row[2]["text"] for mode in ("Watch", "Predict", "Drive"))
        folders = [s for s in row[4]["codes"] if s.startswith("cursus/demos/")]
        if not folders:
            continue
        commands = [s for s in row[5]["codes"] if s.startswith("uv run ")]
        assert commands, f"No runnable fallback for {row[1]['text']}"
        for command in commands:
            result = subprocess.run(shlex.split(command), cwd=SESSION / folders[0],
                                    env={**os.environ, "UV_OFFLINE": "1"},
                                    text=True, capture_output=True, timeout=60)
            assert result.returncode == 0, (command, result.stdout, result.stderr)
            assert result.stdout.strip(), f"Empty fallback output: {command}"
            commands_run += 1
    assert commands_run > 0
