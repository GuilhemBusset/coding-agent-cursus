"""Every fallback command the run-of-show gives for a live demo runs offline and prints something."""
import os
import shlex
import subprocess
from html.parser import HTMLParser
from pathlib import Path

SESSION = Path(__file__).resolve().parents[2]


class Rows(HTMLParser):
    """Each table row's cells, as the <code> strings they hold."""

    def __init__(self):
        super().__init__()
        self.rows: list[list[list[str]]] = []
        self.row: list[list[str]] | None = None
        self.code: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag == "td" and self.row is not None:
            self.row.append([])
        elif tag == "code" and self.row:
            self.code = ""

    def handle_data(self, data):
        if self.code is not None:
            self.code += data

    def handle_endtag(self, tag):
        if tag == "code" and self.code is not None and self.row:
            self.row[-1].append(self.code)
            self.code = None
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = None


def test_run_of_show_fallbacks_work():
    parser = Rows()
    parser.feed((SESSION / "cursus/run-of-show.html").read_text(encoding="utf-8"))
    # The 7-column beat table: column 4 names the demo folder, column 5 its fallback commands.
    fallbacks = {}
    for row in (r for r in parser.rows if len(r) == 7):
        folders = [s for s in row[4] if s.startswith("cursus/demos/")]
        if folders:
            commands = [s for s in row[5] if s.startswith("uv run ")]
            assert commands, f"No runnable fallback for {folders[0]}"
            fallbacks.update(dict.fromkeys((folders[0], command) for command in commands))
    assert fallbacks
    for folder, command in fallbacks:
        result = subprocess.run(shlex.split(command), cwd=SESSION / folder, env={**os.environ, "UV_OFFLINE": "1"},
                                text=True, capture_output=True, timeout=60, check=False)
        assert result.returncode == 0, (command, result.stdout, result.stderr)
        assert result.stdout.strip(), f"Empty fallback output: {command}"
