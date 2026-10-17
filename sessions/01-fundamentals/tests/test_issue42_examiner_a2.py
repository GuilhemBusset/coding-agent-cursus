"""Independent deterministic regeneration using fresh outputs and process environments."""
import os
import subprocess
import sys
from pathlib import Path


RUNS = Path(__file__).resolve().parents[1] / "cursus/fixtures/runs"


def test_a2_regeneration_matches_committed_bytes_without_changing_raw(tmp_path):
    raw = {p.name: p.read_bytes() for p in (RUNS / "raw").iterdir() if p.is_file()}
    generated = []
    for i, (seed, zone) in enumerate((("42", "Europe/Luxembourg"), ("2718", "Pacific/Auckland"))):
        out = tmp_path / f"out-{i}"
        env = dict(os.environ, PYTHONHASHSEED=seed, TZ=zone, PYTHONDONTWRITEBYTECODE="1")
        command = [sys.executable, str(RUNS / "normalize_runs.py"), "--out", str(out)]
        subprocess.run(command, cwd=tmp_path, env=env, check=True)
        outputs = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}
        assert len(outputs) == 6
        assert all((RUNS / name).read_bytes() == content for name, content in outputs.items())
        subprocess.run(command + ["--check"], cwd=tmp_path, env=env, check=True)
        generated.append(outputs)
    assert generated[0] == generated[1]
    assert raw == {p.name: p.read_bytes() for p in (RUNS / "raw").iterdir() if p.is_file()}
