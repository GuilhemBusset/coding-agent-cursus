from pathlib import Path
import json
import subprocess
import sys


def test_mcp_stdio_and_recorded_comparisons():
    demo = Path(__file__).resolve().parents[1] / 'cursus/demos/agent'
    requests = [
        {'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
        {'method': 'notifications/initialized'},
        {'id': 2, 'method': 'tools/list'},
        {'id': 3, 'method': 'tools/call', 'params': {'name': 'bomb_status', 'arguments': {}}},
    ]
    proc = subprocess.run([sys.executable, str(demo / 'context_bomb.py')], input=''.join(
        json.dumps({'jsonrpc': '2.0', **r}) + '\n' for r in requests), text=True, capture_output=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    rows = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [r['id'] for r in rows] == [1, 2, 3]
    init, listing, call = [r['result'] for r in rows]
    assert init['protocolVersion'] == '2025-06-18'
    assert len(listing['tools']) == 5
    assert {t['name'] for t in listing['tools']} == {'bomb_status', *[f'bomb_filler_{i:02d}' for i in range(1, 5)]}
    payload = json.loads(call['content'][0]['text'])
    assert payload['context_characters'] == len(init['instructions']) + sum(len(t['description']) for t in listing['tools'])
    assert payload['context_blocks'] == init['instructions'].count('### Context Bomb Block') + sum(t['description'].count('### Context Bomb Block') for t in listing['tools'])
    assert payload['context_characters'] > 80000
    for cli, method in [('claude', 'context'), ('codex', 'status')]:
        for run in [1, 2]:
            meta = json.loads((demo / f'recorded/bomb-{cli}-run{run}.meta.json').read_text())
            for arm in meta['arms'].values():
                assert arm['answer'] == 'OK' and arm['exit_code'] == 0
            before = (demo / f'recorded/bomb-{cli}-run{run}-{method}-before.txt').read_text()
            after = (demo / f'recorded/bomb-{cli}-run{run}-{method}-after.txt').read_text()
            assert f'/{method}' in before and f'/{method}' in after
            assert 'context_bomb' in after
            if cli == 'claude':
                assert meta['arms']['with']['usage']['total'] > meta['arms']['without']['usage']['total']
                assert meta['arms']['with-tool-search-off']['usage']['total'] > meta['arms']['with']['usage']['total']
