"""D3/A1 CLI regression checks for quoted credentials spanning real newlines.

Only the public CLI is exercised. Inputs are disposable, offline controls, not
recording evidence. Credential values are assembled deterministically at runtime.
Closed values preserve surrounding text; unterminated values consume their unit
(a plain file or one decoded JSON string), retaining its final newline.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SESSION = Path(__file__).resolve().parents[1]
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


def scan(path, expected, hidden=()):
    before = path.read_bytes()
    result = cli("--scan", path, cwd=path.parent)
    assert result.returncode == expected, result.stdout + result.stderr
    assert path.read_bytes() == before, "--scan must never rewrite a file"
    for piece in hidden:
        assert piece not in result.stdout + result.stderr, "scanner echoed a credential"


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


def write_case(tmp_path, case, kind):
    extension = {"text": "txt", "jsonl": "jsonl", "json": "json"}[kind]
    path = tmp_path / ("control." + extension)
    path.write_bytes(encode(case.source, kind))
    return path


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


def sanitize_and_check(path, case, kind):
    success(cli(path, cwd=path.parent))
    once = path.read_bytes()
    assert decoded(once, kind) == decoded(encode(case.cleaned, kind), kind)
    for piece in case.fragments:
        assert piece.encode("utf-8") not in once, "a line of the quoted value survived"
    success(cli(path, cwd=path.parent))
    assert path.read_bytes() == once, "a second sanitize must be byte-identical"
    return once


@pytest.mark.parametrize("kind", FORMATS)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_d3_multiline_quoted_values(tmp_path, scenario, kind):
    case = multiline_case(scenario)
    path = write_case(tmp_path, case, kind)
    original = path.read_bytes()
    once = sanitize_and_check(path, case, kind)
    assert once != original, "the positive control must actually be redacted"
    if kind == "jsonl":
        assert once.splitlines()[1] == original.splitlines()[1]


@pytest.mark.parametrize("kind", FORMATS)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_a1_multiline_scan_agrees_with_sanitize(tmp_path, scenario, kind):
    case = multiline_case(scenario)
    path = write_case(tmp_path, case, kind)
    scan(path, 1, case.fragments)
    sanitize_and_check(path, case, kind)
    scan(path, 0, case.fragments)


@pytest.mark.parametrize("kind", ("text", "jsonl"))
def test_a1_unclosed_placeholder_residue_is_found_and_repaired(tmp_path, kind):
    pieces = fragments("unclosed-placeholder-" + kind)
    prefix = "public preface\n" + "pass" + 'word="'
    # An end-of-line exemption would hide the value that remains on line two.
    case = Case(prefix + "<key>\n" + pieces[1] + '"\nvisible\n',
                prefix + '<key>"\nvisible\n', (pieces[1],))
    path = write_case(tmp_path, case, kind)
    scan(path, 1, case.fragments)
    sanitize_and_check(path, case, kind)
    scan(path, 0, case.fragments)


def test_a1_escaped_quote_residue_is_found_without_echo(tmp_path):
    filler = fragments("escaped-quote-residue")[1]
    name = "pass" + "word"
    # Residue left by stopping at an escaped quote: a placeholder followed by
    # more value text is not a legitimate standalone placeholder.
    residue = '{"' + name + '": "<key>"' + filler + '"}'
    path = tmp_path / "residue.jsonl"
    path.write_text(json.dumps({"type": "tool_result", "content": residue}) + "\n",
                    encoding="utf-8")
    scan(path, 1, (filler,))


@pytest.mark.parametrize("kind", FORMATS)
@pytest.mark.parametrize("quote", ('"', "'", '"""', "'''"))
def test_a1_closed_placeholders_with_later_quotes_are_unchanged(tmp_path, kind, quote):
    name = "tok" + "en"
    text = (name + " = " + quote + "<key>" + quote + "\n"
            + "pass" + 'word="<key>"\nordinary "quoted" words and an apostrophe \'\n'
            + "client_" + "secret = " + quote + "<redacted>" + quote + "\n")
    case = Case(text, text, ())
    path = write_case(tmp_path, case, kind)
    before = path.read_bytes()
    scan(path, 0)
    sanitize_and_check(path, case, kind)
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind", FORMATS)
def test_a1_empty_quoted_value_is_unchanged(tmp_path, kind):
    text = "pass" + 'word=""\nvisible\n'
    case = Case(text, text, ())
    path = write_case(tmp_path, case, kind)
    before = path.read_bytes()
    scan(path, 0)
    sanitize_and_check(path, case, kind)
    assert path.read_bytes() == before


def test_a1_unterminated_jsonl_unit_then_later_apostrophe_scans_clean(tmp_path):
    case = multiline_case("unterminated-single")
    path = write_case(tmp_path, case, "jsonl")
    later = path.read_bytes().splitlines()[1]
    scan(path, 1, case.fragments)
    once = sanitize_and_check(path, case, "jsonl")
    assert once.splitlines()[1] == later
    scan(path, 0, case.fragments)


@pytest.mark.parametrize("extension", ("json", "jsonl"))
def test_d3_multiline_credential_in_decoded_json_key(tmp_path, extension):
    case = multiline_case("triple-single")
    path = tmp_path / ("key-control." + extension)
    original = {"type": "tool_result", "details": {case.source: "ordinary value", "keep": "visible"}}
    expected = {"type": "tool_result", "details": {case.cleaned: "ordinary value", "keep": "visible"}}
    path.write_text(json.dumps(original, indent=2 if extension == "json" else None) + "\n",
                    encoding="utf-8")
    scan(path, 1, case.fragments)
    success(cli(path, cwd=tmp_path))
    once = path.read_bytes()
    assert json.loads(once, object_pairs_hook=tuple) == json.loads(json.dumps(expected), object_pairs_hook=tuple)
    success(cli(path, cwd=tmp_path))
    assert path.read_bytes() == once
    scan(path, 0, case.fragments)


def test_d3_builtin_credential_controls(tmp_path):
    success(cli("--self-test", cwd=tmp_path))
