"""sanitize.py on quoted credentials spanning real newlines, through its public CLI.

Inputs are disposable, offline controls, not recording evidence. Credential values
are assembled deterministically at runtime. Closed values preserve surrounding text;
unterminated values consume their unit (a plain file or one decoded JSON string),
retaining its final newline. Every control is written to one folder, so the scanner
and the sanitizer run a handful of times, not once per control.
"""

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SESSION = Path(__file__).resolve().parents[2]
SANITIZE = SESSION / "cursus/fixtures/runs/sanitize.py"
FORMATS = ("text", "jsonl", "json")
SCENARIOS = (
    "double", "single", "triple-double", "triple-single", "crlf",
    "escaped-double", "escaped-single", "unterminated-double",
    "unterminated-single", "escaped-json-text", "escaped-json-delimiter",
)


@dataclass(frozen=True)
class Case:
    source: str
    cleaned: str
    fragments: tuple[str, ...]


def fragments(label):
    # Several unrelated, non-first-line bodies prevent a fixed example from
    # standing in for redaction of the complete value.
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return tuple("segment-" + digest[i:i + 18] for i in (0, 20, 40))


def multiline_case(scenario):
    pieces = fragments(scenario)
    quote = "'" if scenario in {"single", "escaped-single", "unterminated-single"} else '"'
    if scenario.startswith("triple-"):
        quote = ("'" if scenario.endswith("single") else '"') * 3
    escaped_json = scenario.startswith("escaped-json-")
    if escaped_json:
        quote = "\\" + '"'
    closed = not scenario.startswith("unterminated-")
    newline = "\r\n" if scenario == "crlf" else "\n"
    head = pieces[0]
    if scenario in {"escaped-double", "escaped-single"}:
        head += "\\" + quote
    elif scenario == "escaped-json-delimiter":
        # Inner escaped JSON quote has more backslashes than the delimiter.
        head += "\\" * 3 + '"'
    elif scenario.startswith("triple-"):
        head += " short " + quote[0] + "quoted" + quote[0] + " words"
    body = newline.join((head, pieces[1], pieces[2]))
    name = ("password", "access_token", "client_secret", "api_key")[SCENARIOS.index(scenario) % 4]
    prefix = "public preface\n" + name + " = "
    suffix = "\nvisible trailing text with ordinary words\n"
    if escaped_json:
        prefix = "public preface\nembedded {" + quote + name + quote + ": "
        suffix = ', \\"keep\\": \\"visible\\"}\nvisible trailing text\n'
    if closed:
        return Case(prefix + quote + body + quote + suffix,
                    prefix + quote + "<key>" + quote + suffix, pieces)
    return Case(prefix + quote + body + "\n", prefix + quote + "<key>\n", pieces)


def cli(*args, cwd):
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("GIT_") or key in {"PYTHONPATH", "PYTHONHOME"}:
            env.pop(key, None)
    # Machine-specific git names and login names must not rewrite control prose.
    env.update(CI="1", UV_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_TERMINAL_PROMPT="0", LOGNAME="runner", USER="runner",
               GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="user.name",
               GIT_CONFIG_VALUE_0="runner", GIT_CONFIG_KEY_1="user.email",
               GIT_CONFIG_VALUE_1="")
    return subprocess.run([sys.executable, str(SANITIZE), *map(str, args)],
                          cwd=cwd, env=env, capture_output=True, text=True,
                          timeout=30, check=False)


def success(result):
    assert result.returncode == 0, result.stdout + result.stderr


def wrapper(content):
    return {"type": "tool_result", "content": content,
            "details": {"items": [content, {"note": content}], "keep": "visible"},
            "sequence": 7}


def encode(content, kind):
    if kind == "text":
        return content.encode("utf-8")
    if kind == "jsonl":
        # A later, unrelated quote must never close a value in an earlier unit.
        tail = {"type": "message", "content": "later apostrophe ' and ordinary \"quoted\" words",
                "sequence": 8}
        text = json.dumps(wrapper(content), ensure_ascii=False) + "\n"
        return (text + json.dumps(tail, ensure_ascii=False) + "\n").encode("utf-8")
    return (json.dumps({"events": [wrapper(content)], "keep": "visible"},
                       ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def decoded(data, kind):
    # Object pairs retain key order at every depth while ordinary arrays remain
    # lists. Whitespace/canonicalization is deliberately not part of this test.
    def load(text):
        return json.loads(text, object_pairs_hook=tuple)

    if kind == "text":
        return data.decode("utf-8")
    if kind == "jsonl":
        return [load(line) for line in data.decode("utf-8").splitlines()]
    return load(data)


EXTENSIONS = {"text": "txt", "jsonl": "jsonl", "json": "json"}


def write_case(directory, label, case, kind):
    directory.mkdir(exist_ok=True)
    path = directory / f"{label}.{EXTENSIONS[kind]}"
    path.write_bytes(encode(case.source, kind))
    return path


def scan(tmp_path, *paths):
    """One scanner run: exit code, report, and the files it flagged."""
    result = cli("--scan", *paths, cwd=tmp_path)
    report = result.stdout + result.stderr
    flagged = {Path(line.rsplit(":", 2)[0]) for line in report.splitlines() if line.count(":") >= 2}
    return result.returncode, report, flagged


def snapshot(*directories):
    return {path: path.read_bytes() for directory in directories for path in sorted(directory.iterdir())}


def positive_controls(directory):
    """Each file holds one credential; the value is (expected decoded content, kind, hidden fragments)."""
    controls = {}
    for scenario in SCENARIOS:
        for kind in FORMATS:
            case = multiline_case(scenario)
            path = write_case(directory, f"{scenario}-{kind}", case, kind)
            controls[path] = (decoded(encode(case.cleaned, kind), kind), kind, case.fragments)
    for kind in ("text", "jsonl"):
        # An end-of-line exemption would hide the value that remains on line two.
        pieces = fragments("unclosed-placeholder-" + kind)
        prefix = "public preface\n" + "pass" + 'word="'
        case = Case(prefix + "<key>\n" + pieces[1] + '"\nvisible\n', prefix + '<key>"\nvisible\n', (pieces[1],))
        path = write_case(directory, f"unclosed-placeholder-{kind}", case, kind)
        controls[path] = (decoded(encode(case.cleaned, kind), kind), kind, case.fragments)
    for extension in ("json", "jsonl"):
        # The credential sits in a decoded JSON key, not a value.
        case = multiline_case("triple-single")
        path = directory / f"key-control.{extension}"
        original = {"type": "tool_result", "details": {case.source: "ordinary value", "keep": "visible"}}
        cleaned = {"type": "tool_result", "details": {case.cleaned: "ordinary value", "keep": "visible"}}
        path.write_text(json.dumps(original, indent=2 if extension == "json" else None) + "\n", encoding="utf-8")
        controls[path] = (json.loads(json.dumps(cleaned), object_pairs_hook=tuple), "json", case.fragments)
    return controls


def negative_controls(directory):
    """Closed placeholders, later quotes and empty values: nothing to find, nothing to rewrite."""
    paths = []
    for kind in FORMATS:
        for index, quote in enumerate(('"', "'", '"""', "'''")):
            text = ("tok" + "en" + " = " + quote + "<key>" + quote + "\n"
                    + "pass" + 'word="<key>"\nordinary "quoted" words and an apostrophe \'\n'
                    + "client_" + "secret = " + quote + "<redacted>" + quote + "\n")
            paths.append(write_case(directory, f"placeholders-{index}-{kind}", Case(text, text, ()), kind))
        text = "pass" + 'word=""\nvisible\n'
        paths.append(write_case(directory, f"empty-{kind}", Case(text, text, ()), kind))
    return paths


def test_multiline_credentials_are_found_redacted_once_and_rescanned_clean(tmp_path):
    positives, negatives, residue = tmp_path / "positives", tmp_path / "negatives", tmp_path / "residue"
    controls = positive_controls(positives)
    negative_controls(negatives)
    # Residue left by stopping at an escaped quote: a placeholder followed by
    # more value text is not a legitimate standalone placeholder.
    residue.mkdir()
    filler = fragments("escaped-quote-residue")[1]
    leftover = '{"' + "pass" + "word" + '": "<key>"' + filler + '"}'
    (residue / "residue.jsonl").write_text(json.dumps({"type": "tool_result", "content": leftover}) + "\n",
                                           encoding="utf-8")
    hidden = [piece for _, _, pieces in controls.values() for piece in pieces] + [filler]
    original = snapshot(positives, negatives, residue)

    status, report, flagged = scan(tmp_path, positives, negatives, residue)
    assert status == 1, report
    assert snapshot(positives, negatives, residue) == original, "--scan must never rewrite a file"
    missed = sorted(path.name for path in set(controls) | {residue / "residue.jsonl"} if path not in flagged)
    assert not missed, f"scanner missed {missed}"
    assert not flagged & set(snapshot(negatives)), f"false alarm on {sorted(p.name for p in flagged & set(snapshot(negatives)))}"
    assert not [piece for piece in hidden if piece in report], "scanner echoed a credential"

    success(cli(positives, negatives, cwd=tmp_path))
    once = snapshot(positives, negatives)
    wrong = [path.name for path, (expected, kind, _) in controls.items() if decoded(once[path], kind) != expected]
    assert not wrong, f"wrong redaction in {wrong}"
    survived = [path.name for path, (_, _, pieces) in controls.items() if any(p.encode() in once[path] for p in pieces)]
    assert not survived, f"a line of the quoted value survived in {survived}"
    for path in controls:
        if path.suffix == ".jsonl" and path.name != "key-control.jsonl":
            # The later, unrelated unit is left byte-identical.
            assert once[path].splitlines()[1] == original[path].splitlines()[1], path.name
    changed = [path.name for path in snapshot(negatives) if once[path] != original[path]]
    assert not changed, f"sanitize rewrote clean files {changed}"

    success(cli(positives, negatives, cwd=tmp_path))
    assert snapshot(positives, negatives) == once, "a second sanitize must be byte-identical"
    status, report, _ = scan(tmp_path, positives, negatives)
    assert status == 0, report


def test_d3_builtin_credential_controls(tmp_path):
    success(cli("--self-test", cwd=tmp_path))
