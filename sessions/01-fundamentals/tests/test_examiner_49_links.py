"""Follow only clickable links, and validate files, anchors and replay routes (A1)."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
import json
import re

SESSION = Path(__file__).resolve().parents[1]


class Links(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.ids, self.refs, self.anchors = set(), [], []
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        for key in ("href", "src"):
            if key not in attrs:
                continue
            url = urlsplit(attrs[key])
            if url.scheme or url.netloc:
                continue
            dest = (self.path.parent / unquote(url.path)).resolve()
            if not url.path:
                dest = self.path
            ref = (dest, unquote(url.fragment))
            self.refs.append(ref)
            if tag == "a" and key == "href":
                self.anchors.append(ref)


def test_session_graph_and_targets():
    pages = {p.resolve(): Links(p.resolve()) for p in SESSION.rglob("*.html")
             if not any(s.startswith(".") for s in p.relative_to(SESSION).parts)}
    reached, pending = set(), [(SESSION / "index.html").resolve()]
    while pending:
        page = pending.pop()
        if page in reached:
            continue
        reached.add(page)
        pending.extend(dest for dest, _ in pages[page].anchors
                       if dest in pages and dest not in reached)
    assert set(pages) <= reached, f"Unreachable: {set(pages) - reached}"
    for path, page in pages.items():
        for dest, fragment in page.refs:
            assert dest.exists(), f"{path}: missing {dest}"
            if dest.suffix != ".html" or not fragment:
                continue
            target = pages.get(dest) or Links(dest)
            if fragment.startswith("run="):
                catalogs = re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
                                      dest.read_text(encoding="utf-8"), re.S)
                run_ids = {r.get("id") or r.get("meta", {}).get("run") for data in catalogs
                           for r in json.loads(data).get("runs", [])}
                assert fragment[4:] in run_ids, f"{path}: unknown replay {fragment}"
            else:
                assert fragment in target.ids, f"{path}: missing {dest}#{fragment}"
