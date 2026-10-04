"""Offline HTML contract; independent of the repo's authoring tools."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


SESSION = Path(__file__).resolve().parents[1]
KINDS = {"page", "deck", "lab"}
RESOURCE_RELS = {
    "stylesheet", "icon", "apple-touch-icon", "preload", "modulepreload",
    "prefetch", "manifest",
}


def page_problems(text, path) -> list[str]:
    """Check markers and resource URLs, resolving local URLs beside the page."""
    path = Path(path)
    problems = []

    def resource(value):
        value = value.strip()
        if value.lower().startswith(("http", "//")):
            problems.append(f"{path}: remote resource {value!r}")
            return
        url = urlsplit(value)
        if url.scheme and url.scheme.lower() != "file":
            return  # Embedded data/blob URLs do not import repository files.
        target = (path.parent / unquote(url.path)).resolve()
        if not target.is_relative_to(SESSION):
            problems.append(f"{path}: resource escapes session: {value!r}")

    class PageParser(HTMLParser):
        html_count = 0

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "html":
                self.html_count += 1
                if attrs.get("data-design-system") != "cursus":
                    problems.append(f"{path}: missing data-design-system=\"cursus\"")
                if attrs.get("data-page-kind") not in KINDS:
                    problems.append(f"{path}: invalid data-page-kind")
            if attrs.get("src"):
                resource(attrs["src"])
            if attrs.get("srcset"):
                # Consume URL tokens before descriptors. Commas inside data URLs
                # belong to the URL, whereas trailing commas separate candidates.
                remaining = attrs["srcset"].strip()
                while remaining:
                    remaining = remaining.lstrip(", \t\r\n\f")
                    if not remaining:
                        break
                    parts = remaining.split(None, 1)
                    candidate = parts[0]
                    remaining = parts[1] if len(parts) > 1 else ""
                    if not candidate.lower().startswith("data:"):
                        for entry in candidate.split(","):
                            if entry:
                                resource(entry)
                    if candidate.endswith(","):
                        continue
                    _, separator, remaining = remaining.partition(",")
                    if not separator:
                        remaining = ""
            if tag == "link" and attrs.get("href"):
                rels = set((attrs.get("rel") or "").lower().split())
                if rels & RESOURCE_RELS:
                    resource(attrs["href"])

        handle_startendtag = handle_starttag

    parser = PageParser()
    parser.feed(text)
    parser.close()
    if not parser.html_count:
        problems.append(f"{path}: missing html element and page markers")
    return problems


def test_every_page_follows_the_contract():
    problems = []
    for path in sorted(SESSION.rglob("*.html")):
        if any(part.startswith(".") for part in path.relative_to(SESSION).parts):
            continue
        problems.extend(page_problems(path.read_text(encoding="utf-8"), path))
    assert not problems, "\n".join(problems)


def document(body="", kind="page"):
    return f'<html data-design-system="cursus" data-page-kind="{kind}">{body}</html>'


def test_checker_rejects_missing_markers_and_invalid_kinds():
    for text in (
        "<p>No root element</p>",
        '<html data-page-kind="page"></html>',
        '<html data-design-system="other" data-page-kind="lab"></html>',
        '<html data-design-system="cursus"></html>',
        document(kind="slides"),
        document(kind="PAGE"),
    ):
        assert page_problems(text, SESSION / "cursus/demo.html"), text


def test_checker_rejects_remote_resources():
    for url in ("http://example.invalid/a.js", "HTTPS://example.invalid/b.png", "//cdn.invalid/c"):
        for body in (
            f'<script src="{url}"></script>',
            f'<img src="  {url}">',
            f'<link rel="alternate StyleSheet" href="{url}">',
            f'<source srcset="local.png 1x, {url} 2x">',
            f'<img srcset="{url} 1x, local.png 2x">',
        ):
            assert page_problems(document(body), SESSION / "cursus/demo.html"), body


def test_checker_rejects_resource_escapes_at_different_depths():
    for relative_page, escape in (
        ("index.html", "../shared.js"),
        ("cursus/labs/demo.html", "../../../shared.js"),
        ("cursus/demos/demo.html", "%2e%2e/%2e%2e/%2e%2e/shared.js?rev=1#part"),
    ):
        for body in (
            f'<script src="{escape}"></script>',
            f'<img srcset="ok.png 1x, {escape} 2x">',
            f'<link rel="stylesheet" href="{escape}">',
            f'<link rel="icon" href="{escape}">',
            f'<link rel="preload" href="{escape}">',
        ):
            assert page_problems(document(body), SESSION / relative_page), body


def test_checker_accepts_page_kinds_local_resources_and_reading_links():
    body = '''
        <a href="https://example.invalid/reading">Reading</a>
        <a href="../../../docs/reading.md">Repo reading</a>
        <a href="//example.invalid/reading">More reading</a>
        <script src="../fixtures/demo.js?version=1#start"></script>
        <img src="data:image/png;base64,AAAA">
        <img srcset="../fixtures/a.png 1x, ../fixtures/b.png 2x">
        <img srcset="data:image/png;base64,AAAA 1x, ../fixtures/b.png 2x">
        <link rel="stylesheet" href="../../theme.css">
        <link rel="icon" href="icon.svg">
    '''
    for kind in sorted(KINDS):
        assert page_problems(document(body, kind), SESSION / "cursus/labs/demo.html") == []


def test_checker_ignores_markup_inside_comments():
    text = document('<!-- <script src="https://example.invalid/demo.js"></script> -->')
    assert page_problems(text, SESSION / "index.html") == []
