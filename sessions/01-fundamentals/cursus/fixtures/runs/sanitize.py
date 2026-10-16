"""Strip personal data and credentials from agent-run recordings, or scan for them.

    python sanitize.py [--identity TEXT ...] [--work DIR] [--tmp DIR ...] PATH...
    python sanitize.py --scan [--identity TEXT ...] PATH...

Rewrites every file in place (directories are walked). JSONL files are rewritten line by
line: every string at any depth, keys included, goes through the same rules and the key
order is kept; unchanged lines stay byte-identical. A file holding one JSON document is
rewritten the same way; anything else is plain text. Nothing is ever truncated.

Rules, in order: opaque crypto blobs (`signature`, `encrypted_content` values) become
<redacted>; PEM private keys and the known key families become <key>; email addresses
become <email>; the recording workspace becomes <work> and its temporary root <tmp> (also
in the dash-encoded spelling Claude Code uses for project folders); home folders on Linux,
macOS and Windows become ~, dash-encoded home paths -<work>; identity tokens become <user>
at word boundaries, case-insensitively. The identities are the local login and git
user.name (whole and per word) and user.email, plus every --identity.

--scan never writes. It prints `file:line:category` for each finding, never the finding
itself, and exits 1 if there is any. It checks the same families, the local identities
(skipped when CI is set, since a CI runner has its own), every --identity, and the
sha256 digests listed in scan-identities.json beside this script, which are compared with
every casefolded word and word pair. Exact placeholders are exempt; a placeholder glued to more
text is not. In JSON, the raw line is scanned with its escape sequences blanked (an escape
ends in a letter, so a newline before `@pytest.fixture` would read as an address), and every
decoded string is scanned as it is.
"""

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


HERE = Path(__file__).resolve().parent
IDENTITY_DIGESTS = HERE / "scan-identities.json"
OPAQUE_KEYS = {"signature", "encrypted_content"}
PLACEHOLDERS = ("<work>", "<tmp>", "<user>", "<email>", "<key>", "<redacted>")
# Logins that are also everyday words, or placeholder words, are never treated as names.
NOT_NAMES = {"root", "runner", "user", "admin", "work", "tmp", "key", "email", "redacted"}

# A secret-looking value must not be one of our placeholders standing alone.
NOT_PLACEHOLDER = r"(?!<(?:key|redacted)>(?:$|[\s\"',;}]))"
VALUE = r"[^\s\"',;}]+"
KEY_PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9]+ )?PRIVATE KEY-----")),
    ("github_key", re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{8,}")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{8,}")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}")),
    ("aws_key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    ("slack_key", re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{8,}")),
    ("bearer", re.compile(r"\bBearer\s+" + NOT_PLACEHOLDER + VALUE, re.I)),
    ("assignment", re.compile(r"\b(?:api[_-]?key|token|secret|password)\s*[=:]\s*" + NOT_PLACEHOLDER + VALUE, re.I)),
)
EMAIL = re.compile(r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}")
HOME_PATHS = (
    ("home", re.compile(r"/(?:home|Users)/[\w.-]+", re.I)),
    ("windows_home", re.compile(r"[A-Z]:[\\/]+Users[\\/]+[\w.-]+", re.I)),
)
ENCODED_HOME = re.compile(r"-(?:home|Users)-[\w.-]+", re.I)
# Claude Code names a project folder after its path with every other character as a dash.
ENCODED_HOME_SCAN = re.compile(r"-home-[\w.]+-", re.I)
JSON_ESCAPE = re.compile(r"\\(?:u[0-9a-fA-F]{4}|[\"\\/bfnrt])")


def local_identities():
    """Login, git user.name (whole and per word) and git user.email of this machine."""
    values = set()
    try:
        values.add(getpass.getuser())
    except (KeyError, OSError):
        pass
    for key in ("user.name", "user.email"):
        try:
            result = subprocess.run(["git", "config", "--get", key], cwd=HERE,
                                    capture_output=True, text=True, timeout=10)
        except OSError:
            continue
        text = result.stdout.strip() if result.returncode == 0 else ""
        if text:
            values.add(text)
            if key == "user.name":
                values.update(text.split())
    return {value for value in values if len(value) >= 3 and value.casefold() not in NOT_NAMES}


def encoded(path):
    return re.sub(r"[^A-Za-z0-9]", "-", path)


class Sanitizer:
    def __init__(self, identities=(), work=None, tmp=()):
        self.paths = []
        for path, placeholder in ((work, "<work>"), *((folder, "<tmp>") for folder in tmp)):
            if path:
                for spelling in {str(Path(path)), str(Path(path).resolve())}:
                    self.paths.append((spelling, placeholder))
                    self.paths.append((encoded(spelling), "-" + placeholder if placeholder == "<work>" else placeholder))
        # Longest first, so a workspace inside the temporary root wins over the root.
        self.paths.sort(key=lambda pair: -len(pair[0]))
        home = str(Path.home())
        self.home = home if home not in {"/", "."} and len(home) > 1 else None
        tokens = sorted({token.strip() for token in identities if token.strip()}, key=lambda t: (-len(t), t))
        self.identities = [re.compile(r"(?<!\w)" + re.escape(token) + r"(?!\w)", re.I) for token in tokens]

    def text(self, value):
        for _, pattern in KEY_PATTERNS:
            value = pattern.sub("<key>", value)
        value = EMAIL.sub("<email>", value)
        for spelling, placeholder in self.paths:
            value = value.replace(spelling, placeholder)
        if self.home:
            value = value.replace(self.home, "~")
        for _, pattern in HOME_PATHS:
            value = pattern.sub("~", value)
        value = ENCODED_HOME.sub("-<work>", value)
        for pattern in self.identities:
            value = pattern.sub("<user>", value)
        return value

    def value(self, value, key=None):
        if isinstance(value, str):
            if key in OPAQUE_KEYS and value:
                return "<redacted>"
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(k): self.value(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self.value(child) for child in value]
        return value

    def file(self, path):
        original = path.read_text(encoding="utf-8")
        document = parse(original)
        if path.name.endswith(".jsonl"):
            result = "\n".join(self.line(line) for line in original.split("\n"))
        elif document is not None:
            cleaned = self.value(document)
            result = original if cleaned == document else dump_document(cleaned)
        else:
            # Whole text at once, so a key block spanning several lines is caught.
            result = self.text(original)
        if result != original:
            path.write_text(result, encoding="utf-8", newline="")
        return result != original

    def line(self, line):
        value = parse(line)
        if value is None:
            return self.text(line)
        cleaned = self.value(value)
        if cleaned == value:
            return line
        return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def parse(text):
    if not text.strip():
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, (dict, list)) else None


def dump_document(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def files(paths):
    for path in paths:
        path = Path(path)
        if path.is_dir():
            yield from (child for child in sorted(path.rglob("*")) if child.is_file() or child.is_symlink())
        else:
            yield path


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def words(text):
    found = re.findall(r"\w+", text.casefold())
    yield from found
    yield from (" ".join(pair) for pair in zip(found, found[1:]))


class Scanner:
    def __init__(self, identities=()):
        self.identities = sorted({token.casefold() for token in identities if token.strip()})
        self.digests = set()
        if IDENTITY_DIGESTS.is_file():
            self.digests = set(json.loads(IDENTITY_DIGESTS.read_text(encoding="utf-8")))
        home = str(Path.home())
        self.home = home if home not in {"/", "."} and len(home) > 1 else None

    def categories(self, text):
        found = {name for name, pattern in KEY_PATTERNS if pattern.search(text)}
        found.update(name for name, pattern in HOME_PATHS if pattern.search(text))
        if EMAIL.search(text):
            found.add("email")
        if ENCODED_HOME_SCAN.search(text):
            found.add("encoded_home")
        if self.home and self.home in text:
            found.add("local_home")
        folded = text.casefold()
        if any(re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", folded) for token in self.identities):
            found.add("identity")
        if self.digests and any(sha(word) in self.digests for word in words(text)):
            found.add("recorded_identity")
        return found

    def file(self, path, root):
        findings = []
        if path.is_symlink() and root is not None and not path.resolve().is_relative_to(root.resolve()):
            return [(0, "escaping_symlink")]
        text = path.read_text(encoding="utf-8", errors="replace")
        document = parse(text)
        for number, line in enumerate(text.split("\n"), 1):
            value = parse(line)
            # In JSON, an escape such as a newline's ends in a letter, so a decorator right after
            # it reads as an address. The raw pass skips escapes; decoded strings are scanned as-is.
            raw = JSON_ESCAPE.sub(" ", line) if value is not None or document is not None else line
            categories = self.categories(raw)
            if value is not None:
                for item in strings(value):
                    categories |= self.categories(item)
            findings.extend((number, category) for category in sorted(categories))
        for name, pattern in KEY_PATTERNS:
            for match in pattern.finditer(text):
                if "\n" in match.group():
                    findings.append((text.count("\n", 0, match.start()) + 1, name))
        if document is not None and "\n" in text.strip():
            categories = set()
            for item in strings(document):
                categories |= self.categories(item)
            # Decoded strings of a multi-line document have no single line; report line 0.
            reported = {category for _, category in findings}
            findings.extend((0, category) for category in sorted(categories - reported))
        return findings


def scan(paths, identities):
    scanner = Scanner(identities)
    total = 0
    for root in map(Path, paths):
        base = root if root.is_dir() else None
        for path in files([root]):
            for number, category in scanner.file(path, base):
                print(f"{path}:{number}:{category}")
                total += 1
    return 1 if total else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scan", action="store_true", help="report findings instead of rewriting")
    parser.add_argument("--identity", action="append", default=[], help="extra name, login or email to remove")
    parser.add_argument("--work", help="recording workspace, replaced by <work>")
    parser.add_argument("--tmp", action="append", default=[], help="temporary folder of the recording, replaced by <tmp>")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)
    if args.scan:
        live = local_identities() if not os.environ.get("CI") else set()
        return scan(args.paths, live | set(args.identity))
    sanitizer = Sanitizer(local_identities() | set(args.identity), work=args.work, tmp=args.tmp)
    for path in files(args.paths):
        if path.is_file() and not path.is_symlink():
            sanitizer.file(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
