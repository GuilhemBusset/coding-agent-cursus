"""Re-embed the stories260K checkpoint and tok512 tokenizer into ../tiny-lm.html.

Instructor tooling, Linux only. Standard library only, so it runs with any Python 3.12:

    python3 sessions/01-fundamentals/cursus/labs/tiny-lm/embed_weights.py
    python3 .../embed_weights.py --source-dir DIR   # use files already downloaded into DIR

It downloads both files from the immutable Hugging Face URLs pinned in provenance.json,
refuses any file whose byte length or sha256 differs from the recorded values, and rewrites
only the two <script type="application/octet-stream"> data blocks: base64 wrapped at 120
columns, with data-sha256 set to the sha256 of the decoded bytes.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import urllib.request

HERE = Path(__file__).resolve().parent
PAGE = HERE.parent / "tiny-lm.html"
PROVENANCE = HERE / "provenance.json"
WRAP = 120
BLOCKS = {"weights": "tiny-lm-weights", "tokenizer": "tiny-lm-tokenizer"}


def load(record, source_dir):
    name = record["url"].rsplit("/", 1)[1]
    if source_dir:
        data = (Path(source_dir) / name).read_bytes()
    else:
        with urllib.request.urlopen(record["url"], timeout=60) as response:
            data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != record["bytes"] or digest != record["sha256"]:
        raise SystemExit(
            f"{name}: got {len(data)} bytes, sha256 {digest}; "
            f"provenance.json pins {record['bytes']} bytes, sha256 {record['sha256']}"
        )
    return data


def block(element_id, data):
    encoded = base64.b64encode(data).decode("ascii")
    lines = "\n".join(encoded[i:i + WRAP] for i in range(0, len(encoded), WRAP))
    digest = hashlib.sha256(data).hexdigest()
    return (
        f'<script type="application/octet-stream" id="{element_id}" data-sha256="{digest}">\n'
        f"{lines}\n</script>"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source-dir", help="read stories260K.bin and tok512.bin from here")
    args = parser.parse_args()
    files = json.loads(PROVENANCE.read_text(encoding="utf-8"))["model"]["files"]
    html = PAGE.read_text(encoding="utf-8")
    for key, element_id in BLOCKS.items():
        pattern = re.compile(
            r'<script type="application/octet-stream" id="' + element_id + r'"[^>]*>.*?</script>',
            re.DOTALL,
        )
        if len(pattern.findall(html)) != 1:
            raise SystemExit(f"expected exactly one #{element_id} data block in {PAGE.name}")
        replacement = block(element_id, load(files[key], args.source_dir))
        html = pattern.sub(lambda _: replacement, html)
    PAGE.write_text(html, encoding="utf-8")
    print(f"Embedded weights and tokenizer into {PAGE} ({PAGE.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
