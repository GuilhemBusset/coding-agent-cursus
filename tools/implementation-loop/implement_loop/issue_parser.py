"""Turn an issue body into a ledger, a branch, declared paths and a stable hash.

Bodies follow the shape the Session 1 issues use: `## Deliverables` and `## Acceptance
criteria` sections of checkboxes, a `Suggested branch:` line, and a `## References` list.
"""

from __future__ import annotations

import hashlib
import re

from .config import REPO_TOP_LEVEL
from .model import Issue, IssueSpec, LedgerItem

_HEADING = re.compile(r"^##\s+(.+?)\s*$")
_CHECKBOX = re.compile(r"^\s*[-*]\s+\[( |x|X)\]\s+(.*\S)\s*$")
_BRANCH = re.compile(r"Suggested branch:\s*`([^`]+)`")
_TOKEN = re.compile(r"`([^`]+)`")
_PATHLIKE = re.compile(r"^[A-Za-z0-9_.\-/]+$")
_EVIDENCE_SUFFIX = re.compile(r"\s+\(\[evidence\]\([^)]*\)\)\s*$")
_SECTION_KEYS = {"deliverables": "deliverable", "acceptance criteria": "acceptance"}


def sections(body: str) -> dict[str, list[str]]:
    """Split a body into `## ` sections, keyed by lower-cased heading."""
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        m = _HEADING.match(line)
        if m:
            current = m.group(1).strip().lower()
            out.setdefault(current, [])
        elif line.lstrip().startswith("<details"):
            current = None  # collapsed blocks (e.g. agent conventions) belong to no section
        elif current is not None:
            out[current].append(line)
    return out


def ledger(body: str) -> list[LedgerItem]:
    items: list[LedgerItem] = []
    for heading, lines in sections(body).items():
        section = _SECTION_KEYS.get(heading)
        if not section:
            continue
        prefix = "D" if section == "deliverable" else "A"
        n = 0
        for line in lines:
            m = _CHECKBOX.match(line)
            if not m:
                continue
            n += 1
            text = _EVIDENCE_SUFFIX.sub("", m.group(2))
            items.append(LedgerItem(id=f"{prefix}{n}", section=section, text=text, checked=m.group(1) != " "))
    return items


def normalize_body(body: str) -> str:
    """The body as authored: ticks and evidence links the engine adds are removed.

    The engine ticks checkboxes itself, so hashing the raw body would make every tick look
    like a changed requirement.
    """
    out = []
    for line in body.replace("\r\n", "\n").splitlines():
        m = _CHECKBOX.match(line)
        if m:
            indent = line[: len(line) - len(line.lstrip())]
            line = f"{indent}- [ ] {_EVIDENCE_SUFFIX.sub('', m.group(2))}"
        out.append(line.rstrip())
    return "\n".join(out).strip() + "\n"


def body_hash(body: str) -> str:
    return hashlib.sha256(normalize_body(body).encode()).hexdigest()


_DOT_DIRS = (".github/", ".claude/", ".agents/", ".githooks/", ".gitignore")
_FILE_EXT = re.compile(r"[A-Za-z_\-][A-Za-z0-9_\-]*\.[A-Za-z0-9]{1,5}$")


def _is_path(token: str) -> bool:
    if not _PATHLIKE.match(token) or token.startswith(("-", "/")) or token.endswith("."):
        return False
    if token.startswith(".") and not token.startswith(_DOT_DIRS):
        return False
    return "/" in token or bool(_FILE_EXT.search(token))


def resolve_path(token: str, session_dir: str | None) -> str:
    if token.startswith(REPO_TOP_LEVEL) or session_dir is None:
        return token
    return f"{session_dir.rstrip('/')}/{token}"


def declared_paths(body: str, session_dir: str | None = None) -> list[str]:
    """Paths named in the Deliverables section, resolved against the session folder."""
    found: list[str] = []
    for line in sections(body).get("deliverables", []):
        for token in _TOKEN.findall(line):
            if _is_path(token):
                path = resolve_path(token, session_dir)
                if path not in found:
                    found.append(path)
    return found


def reference_paths(body: str) -> list[str]:
    """Local (non-URL) paths in the References section; they must exist when work starts."""
    found = []
    for line in sections(body).get("references", []):
        if "](" in line:
            continue
        for token in _TOKEN.findall(line):
            if _is_path(token) and token not in found:
                found.append(token)
    return found


def suggested_branch(body: str) -> str | None:
    m = _BRANCH.search(body)
    return m.group(1).strip() if m else None


_SESSION_DIR = re.compile(r"\bsessions/(\d{2}-[A-Za-z0-9_-]+)")


def mentioned_session_dirs(body: str) -> list[str]:
    return sorted({f"sessions/{m}" for m in _SESSION_DIR.findall(body)})


def session_dir_for(issue: Issue, known_session_dirs: list[str]) -> str | None:
    """The session folder of an issue labelled `session:NN`: an existing folder, else one the
    issue (or another issue in the run) names, else `sessions/NN`."""
    for label in issue.labels:
        if label.startswith("session:"):
            nn = label.split(":", 1)[1]
            for d in known_session_dirs + mentioned_session_dirs(issue.body):
                if d.split("/")[-1].startswith(f"{nn}-"):
                    return d
            return f"sessions/{nn}"
    return None


def parse(issue: Issue, existing_session_dirs: list[str] | None = None) -> IssueSpec:
    session_dir = session_dir_for(issue, existing_session_dirs or [])
    return IssueSpec(
        number=issue.number,
        ledger=ledger(issue.body),
        branch=suggested_branch(issue.body),
        declared_paths=declared_paths(issue.body, session_dir),
        reference_paths=reference_paths(issue.body),
        body_hash=body_hash(issue.body),
    )


def tick(body: str, item_ids_to_links: dict[str, str]) -> str:
    """Tick ledger checkboxes by id, appending an evidence link. Untouched lines stay as is."""
    out = []
    current_section: str | None = None
    counters = {"deliverable": 0, "acceptance": 0}
    for line in body.splitlines():
        h = _HEADING.match(line)
        if h:
            current_section = _SECTION_KEYS.get(h.group(1).strip().lower())
            out.append(line)
            continue
        m = _CHECKBOX.match(line)
        if m and current_section:
            counters[current_section] += 1
            item_id = ("D" if current_section == "deliverable" else "A") + str(counters[current_section])
            if item_id in item_ids_to_links:
                indent = line[: len(line) - len(line.lstrip())]
                text = _EVIDENCE_SUFFIX.sub("", m.group(2))
                link = item_ids_to_links[item_id]
                line = f"{indent}- [x] {text}" + (f" ([evidence]({link}))" if link else "")
        out.append(line)
    return "\n".join(out) + ("\n" if body.endswith("\n") else "")
