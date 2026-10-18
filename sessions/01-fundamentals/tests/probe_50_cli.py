"""Independent D1 witness: the sampling claim against the real CLI interfaces."""
from pathlib import Path
import re
import subprocess

SESSION = Path(__file__).resolve().parents[1]

def test_sampling_claim_matches_both_installed_cli_interfaces():
    deck = (SESSION / 'cursus/01-sampler.html').read_text(encoding='utf-8')
    if not re.search(r'neither CLI exposes a temperature, top-p or seed option', deck, re.I):
        return  # Removing the unsupported claim is also an allowed D1 outcome.
    for command in (['claude', '--help'], ['codex', '--help'], ['codex', 'exec', '--help']):
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        flags = set(re.findall(r'--[a-z][a-z0-9-]*', result.stdout))
        assert not flags.intersection({'--temperature', '--top-p', '--top_p', '--seed'}), (command, flags)
