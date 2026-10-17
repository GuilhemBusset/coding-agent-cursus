"""Strip personal data and credentials from agent-run recordings, or scan for them.

    python sanitize.py [--identity TEXT ...] [--work DIR] [--tmp DIR ...] PATH...
    python sanitize.py --scan [--identity TEXT ...] PATH...
    python sanitize.py --self-test            # positive and negative controls of the key rules

Rewrites every file in place (directories are walked). JSONL files are rewritten line by
line: every string at any depth, keys included, goes through the same rules and the key
order is kept; unchanged lines stay byte-identical. A file holding one JSON document is
rewritten the same way; anything else is plain text. Nothing is ever truncated.

Rules, in order: opaque crypto blobs (`signature`, `encrypted_content` values) become
<redacted>; a JSON string field named like a credential (`token`, `api_key`, `password`,
`secret`, also as a suffix such as `access_token`) becomes <key>; PEM private keys, the
known key families become <key>, and so does the value of a credential assignment, bare
or quoted, or of a JSON credential field inside text, keeping its name and quotes
(`password: '<key>'`). A quoted value, triple quotes included, runs to its own closing quote
across lines; with none it runs to the end of the text or decoded string. Email addresses
become <email>; the recording workspace becomes <work> and its temporary root <tmp> (also
in the dash-encoded spelling Claude Code uses for project folders); home folders on Linux,
macOS and Windows become ~, dash-encoded home paths -<work>; identity tokens become <user>
at word boundaries, case-insensitively. The identities are the local login and git
user.name (whole and per word) and user.email, plus every --identity.

--scan never writes. It prints `file:line:category` for each finding, never the finding
itself, and exits 1 if there is any. It checks the same families, the local identities
(skipped when CI is set, since a CI runner has its own), every --identity, and the
sha256 digests listed in scan-identities.json beside this script, which are compared with
every casefolded word and word pair. Exact placeholders are exempt when their closing quote or
the end of the text follows; a placeholder glued to more text, or followed by more value on
the next line, is not. In JSON, the raw line is scanned with its escape sequences blanked (an
escape ends in a letter, so a newline before `@pytest.fixture` would read as an address), and
every decoded string is scanned as it is. Credential assignments are matched only where the
sanitizer rewrites them: in every line and the whole text of a plain file, in non-JSON lines of
a JSONL file, and in decoded JSON strings, never across a raw JSON line.
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
import tempfile


HERE = Path(__file__).resolve().parent
IDENTITY_DIGESTS = HERE / "scan-identities.json"
OPAQUE_KEYS = {"signature", "encrypted_content"}
PLACEHOLDERS = ("<work>", "<tmp>", "<user>", "<email>", "<key>", "<redacted>")
# Logins that are also everyday words, or placeholder words, are never treated as names.
NOT_NAMES = {"root", "runner", "user", "admin", "work", "tmp", "key", "email", "redacted"}

# A secret-looking value must not be one of our placeholders standing alone.
NOT_PLACEHOLDER = r"(?!<(?:key|redacted)>(?:$|[\s\"',;}]))"
VALUE = r"[^\s\"',;}]+"
# Names that carry a credential, also as the last part of a longer one (access_token, OPENAI_API_KEY).
CREDENTIAL = r"(?:api[_-]?key|token|secret|password|passwd)"
CREDENTIAL_KEY = re.compile(r"(?:.*[_-])?" + CREDENTIAL, re.I)
# `name = value`, `name: "value"`, `"name": "value"`. A quoted name (a JSON field) needs a quoted
# value, so `"token": null` or `"token": {` is not a finding; a bare name takes either.
# A quoted value (single, double or triple quotes) ends at its own closing quote, never at an
# escaped one inside it, and may span lines (LF or CRLF): a plain quote (`"a\"b"`) is read escape
# by escape; an escaped quote, as in JSON held in a JSON string (`\"a\\\"b\"`), closes only behind
# exactly its own backslashes, since a quote escaped inside the value always has more. With no
# closing quote the value runs to the end of the unit being sanitized (the whole text, or one
# decoded JSON string), keeping a final newline, so an odd value is masked too much rather than
# too little. A placeholder exempts a value only when its closing quote or the end of the unit
# follows it; `"<key>"rest"` and `"<key>` with more value on the next line are still findings.
END = r"(?=\r?\n?\Z)"
AFTER = r"(?=\Z|[\s,;:)}\]'\"`])"
QUOTED = (
    r"(?P<quote>\"\"\"|'''|[\"'])(?!(?P=quote))(?!<(?:key|redacted)>(?:(?P=quote)" + AFTER + "|" + END + "))"
    r"(?:\\[\s\S]|[^\\])+?(?:(?P<shut>(?P=quote))|" + END + ")"
    r"|(?P<esc>\\+)(?P<escquote>[\"'])(?!(?P=esc)(?P=escquote))"
    r"(?!<(?:key|redacted)>(?:(?P=esc)(?P=escquote)(?:" + AFTER + r"|(?=\\[nrt]))|" + END + "))"
    r"[\s\S]+?(?:(?<!\\)(?P<escshut>(?P=esc)(?P=escquote))|" + END + ")"
)
ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9])" + CREDENTIAL + r"(?P<close>\\*[\"'])?\s*[=:]\s*"
    r"(?P<value>" + QUOTED + r"|(?(close)(?!)|" + NOT_PLACEHOLDER + r"(?![{\[(])" + VALUE + r"))", re.I)
KEY_PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9]+ )?PRIVATE KEY-----")),
    ("github_key", re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{8,}")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{8,}")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}")),
    ("aws_key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    ("slack_key", re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{8,}")),
    ("bearer", re.compile(r"\bBearer\s+" + NOT_PLACEHOLDER + VALUE, re.I)),
    ("assignment", ASSIGNMENT),
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


def mask_assignment(match):
    """Keep the name and the quotes of `name = "value"`; only the value becomes <key>."""
    if match.group("quote"):
        masked = match.group("quote") + "<key>" + (match.group("shut") or "")
    elif match.group("esc"):
        masked = match.group("esc") + match.group("escquote") + "<key>" + (match.group("escshut") or "")
    else:
        masked = "<key>"
    return match.group()[:match.start("value") - match.start()] + masked


def is_credential_field(key, value):
    return (isinstance(key, str) and CREDENTIAL_KEY.fullmatch(key) is not None
            and isinstance(value, str) and value.strip() != "" and value not in PLACEHOLDERS)


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
            value = pattern.sub(mask_assignment if pattern is ASSIGNMENT else "<key>", value)
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
            if is_credential_field(key, value):
                return "<key>"
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(k): self.value(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self.value(child) for child in value]
        return value

    def file(self, path):
        # Bytes, so a CRLF is kept as it is rather than translated.
        original = path.read_bytes().decode("utf-8")
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


def credential_fields(value):
    """True if a decoded JSON value holds a credential-named field with a real string value."""
    if isinstance(value, dict):
        return any(is_credential_field(key, child) or credential_fields(child) for key, child in value.items())
    if isinstance(value, list):
        return any(credential_fields(child) for child in value)
    return False


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

    def categories(self, text, assignments=True):
        found = {name for name, pattern in KEY_PATTERNS
                 if (assignments or pattern is not ASSIGNMENT) and pattern.search(text)}
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
        text = path.read_bytes().decode("utf-8", errors="replace")
        document = parse(text)
        jsonl = path.name.endswith(".jsonl")
        plain = not jsonl and document is None
        for number, line in enumerate(text.split("\n"), 1):
            value = parse(line)
            # In JSON, an escape such as a newline's ends in a letter, so a decorator right after
            # it reads as an address. The raw pass skips escapes; decoded strings are scanned as-is.
            raw = JSON_ESCAPE.sub(" ", line) if value is not None or document is not None else line
            categories = self.categories(raw, assignments=False)
            # Assignments are matched only in the units the sanitizer rewrites: a line of plain
            # text or a non-JSON line of a JSONL file, and every decoded JSON string. A raw JSON
            # line would let a value run past its own string into the next one.
            if (plain or (jsonl and value is None)) and ASSIGNMENT.search(line):
                categories.add("assignment")
            if value is not None:
                for item in strings(value):
                    categories |= self.categories(item, assignments=not plain)
                if credential_fields(value):
                    categories.add("credential_field")
            findings.extend((number, category) for category in sorted(categories))
        for name, pattern in KEY_PATTERNS:
            if pattern is ASSIGNMENT and not plain:
                continue
            for match in pattern.finditer(text):
                if "\n" in match.group():
                    findings.append((text.count("\n", 0, match.start()) + 1, name))
        if document is not None and "\n" in text.strip():
            categories = set()
            for item in strings(document):
                categories |= self.categories(item, assignments=not jsonl)
            if credential_fields(document):
                categories.add("credential_field")
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


def self_test():
    """Positive and negative controls for the credential rules; returns the failed control names.

    Every secret-looking value is assembled at run time, so this file holds none itself.
    """
    filler = "Q7n8r9T0u1V2w3X4y5Z6"
    api, tok, pw, sec = "api_" + "key", "tok" + "en", "pass" + "word", "sec" + "ret"
    positives = {
        "double_quoted": f'{api}="{filler}"',
        "single_quoted": f"{pw}='{filler}'",
        "spaced_quoted": f'{tok.upper()} : "{filler}"',
        "bare": f"{tok}={filler}",
        "env_name": f"export OPENAI_{api.upper()}={filler}",
        "suffix_name": f"client_{sec} = '{filler}'",
        "json_in_text": json.dumps({tok: filler}),
        "json_in_text_suffix": json.dumps({"access_" + tok: filler}),
        # The secret sits after an escaped quote inside the value, so stopping there would leak it.
        "escaped_quote": f'{pw}="prefix\\"{filler}"',
        "json_escaped_quote": json.dumps({pw: 'prefix"' + filler, "keep": "visible"}),
        "json_in_json_escaped_quote": json.dumps({"x": json.dumps({pw: 'prefix"' + filler})}),
        "backslash_before_close": json.dumps({pw: filler + "\\", "keep": "visible"}),
        "unterminated": f'{tok}="{filler}',
        # Values spanning lines: the whole filler sits on a later line of the value.
        "multiline_double": f'{pw} = "first\n{filler}\nlast"\nvisible',
        "multiline_single": f"{tok}: 'first\n{filler}'\nvisible",
        "triple_double": f'{sec} = """first "quoted" words\n{filler}\n"""\nvisible',
        "triple_single": f"{api} = '''first\n{filler}'''\nvisible",
        "crlf": f'{pw}="first\r\n{filler}\r\nlast"\r\nvisible',
        "escaped_delimiter_newline": f'{pw}="first\\"\n{filler}"\nvisible',
        "unterminated_multiline": f'{tok}="first\n{filler}\nlast',
        "json_in_text_newline": 'embedded {\\"' + pw + '\\": \\"first\n' + filler + '\\", \\"keep\\": \\"visible\\"}',
    }
    # Embedded JSON is the usual form of tool output: a credential in it must not survive either.
    embedded = json.dumps({pw: 'prefix"' + filler})
    fields = {"json_field": {tok: filler}, "json_nested_field": {"auth": {api: filler}},
              "json_list_field": [{"refresh_" + tok: filler}],
              "tool_result_escaped_quote": {"type": "tool_result", "content": embedded},
              "tool_result_nested_escaped_quote": {"type": "tool_result", "content": json.dumps({"x": embedded})},
              "tool_result_multiline": {"type": "tool_result", "content": f'{pw} = "first\n{filler}"\nvisible'}}
    # Text after a value that closes properly is kept.
    kept = {"json_escaped_quote", "backslash_before_close", "multiline_double", "multiline_single",
            "triple_double", "triple_single", "crlf", "escaped_delimiter_newline", "json_in_text_newline",
            "tool_result_multiline"}
    # What a sanitizer that stopped too early left behind: the scan must still see it, and
    # sanitizing again repairs it. One stopped at an escaped quote, the others at a line end.
    unclosed = f'{pw}="<key>\n{filler}"\nvisible'
    residues = [("residue.jsonl", json.dumps({"content": "{\"" + pw + "\": \"<key>\"" + filler + "\"}"}), False),
                ("residue.txt", unclosed, True),
                ("residue.jsonl", json.dumps({"type": "tool_result", "content": unclosed}), True)]
    negatives = [f'"{tok}": null', f"max_{tok}s=4", '"output_' + tok + 's": 12', f'"{tok}": {{"type": "string"}}',
                 f'{pw}=""', f"{tok}=<key>", f'{api}="<key>"', f"{pw}: '<key>'", json.dumps({tok: "<key>"}),
                 json.dumps({"x": json.dumps({tok: "<key>"})}), f"`{pw}: '<key>'`",
                 f'{tok} = """<key>"""', f'{pw}="<key>"\nordinary "quoted" words']
    failed = []
    sanitizer, scanner = Sanitizer(), Scanner()
    with tempfile.TemporaryDirectory() as folder:
        cases = [(name, "case.txt", text) for name, text in positives.items()]
        cases += [(name, "case.jsonl", json.dumps(value) + "\n") for name, value in fields.items()]
        # An unterminated value ends with its own decoded string: a later line's apostrophe
        # must neither close it nor make the sanitized file a finding.
        later = json.dumps({"type": "message", "content": "an apostrophe ' later"})
        cases.append(("tool_result_unterminated_then_apostrophe", "case.jsonl",
                      json.dumps({"type": "tool_result", "content": f"{pw} = 'first\n{filler}\n"}) + "\n" + later))
        for name, filename, text in cases:
            path = Path(folder) / filename
            path.write_text(text + "\n", encoding="utf-8")
            if not {category for _, category in scanner.file(path, None)} & {"assignment", "credential_field"}:
                failed.append(f"{name}: not found by the scan")
            sanitizer.file(path)
            once = path.read_text(encoding="utf-8")
            if filler in once or scanner.file(path, None):
                failed.append(f"{name}: survives sanitizing")
            if name in kept and "visible" not in once:
                failed.append(f"{name}: sanitizing masks text after the value")
            sanitizer.file(path)
            if path.read_text(encoding="utf-8") != once:
                failed.append(f"{name}: sanitizing is not idempotent")
            if filename.endswith(".jsonl") and any(parse(line) is None for line in once.splitlines() if line.strip()):
                failed.append(f"{name}: sanitized line is not JSON")
        for index, text in enumerate(negatives):
            path = Path(folder) / "negative.txt"
            path.write_text(text + "\n", encoding="utf-8")
            if scanner.file(path, None):
                failed.append(f"negative {index}: reported by the scan")
            if sanitizer.file(path):
                failed.append(f"negative {index}: rewritten by the sanitizer")
        for index, (filename, text, repairable) in enumerate(residues):
            path = Path(folder) / filename
            path.write_text(text + "\n", encoding="utf-8")
            if not scanner.file(path, None):
                failed.append(f"residue {index}: not found by the scan")
            if not repairable:
                continue
            sanitizer.file(path)
            if filler in path.read_text(encoding="utf-8") or scanner.file(path, None):
                failed.append(f"residue {index}: not repaired by sanitizing")
    return failed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--self-test", action="store_true", help="run the credential-rule controls and exit")
    parser.add_argument("--scan", action="store_true", help="report findings instead of rewriting")
    parser.add_argument("--identity", action="append", default=[], help="extra name, login or email to remove")
    parser.add_argument("--work", help="recording workspace, replaced by <work>")
    parser.add_argument("--tmp", action="append", default=[], help="temporary folder of the recording, replaced by <tmp>")
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        failed = self_test()
        print("\n".join(failed) if failed else "credential controls: ok")
        return 1 if failed else 0
    if not args.paths:
        parser.error("PATH is required")
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
