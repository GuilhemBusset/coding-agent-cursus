"""Independent scan of decoded fixture contents and the delivered scanner."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


RUNS = Path(__file__).resolve().parents[1] / "cursus/fixtures/runs"


def texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from texts(child)
    elif isinstance(value, list):
        for child in value:
            yield from texts(child)


def test_a1_no_private_paths_keys_emails_or_recording_identities():
    patterns = [r"/(?:home|Users)/[\w.-]+", r"[A-Za-z]:[\\/]+Users[\\/]+[\w.-]+",
                r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}",
                r"\b(?:sk-(?:ant-|proj-)?|gh[pousr]_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{8,}",
                r"\bAKIA[A-Z0-9]{16}\b"]
    hashes = set(json.loads((RUNS / "scan-identities.json").read_text()))
    for path in sorted(RUNS.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".jsonl":
            parts = [t for line in text.splitlines() for t in texts(json.loads(line))]
        elif path.suffix == ".json":
            parts = list(texts(json.loads(text)))
        else:
            parts = [text]
        for part in parts:
            assert not any(re.search(p, part) for p in patterns), f"Privacy pattern in {path.name}"
            words = re.findall(r"\w+", part.casefold())
            candidates = words + [" ".join(pair) for pair in zip(words, words[1:])]
            assert not any(hashlib.sha256(w.encode()).hexdigest() in hashes for w in candidates), f"Identity in {path.name}"
    result = subprocess.run([sys.executable, str(RUNS / "sanitize.py"), "--scan", str(RUNS)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
