"""Validate actual diagnostic artifacts against the existing session contracts."""

import json
import subprocess
import sys
from pathlib import Path

SESSION = Path(__file__).resolve().parents[2]
ROOT = SESSION.parents[1]


def test_offline_endpoint_diagnostic_emits_contract_valid_trace_and_unknown_totals():
    result = subprocess.run(
        [sys.executable, str(ROOT / 'setup/session-02-research-agents.py'),
         '--adapter-smoke', '--offline'], cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['success'] and report['evidence_kind'] == 'synthetic'
    assert report['tool_results'] == 1 and report['offline_continuation_received']
    assert report['timeout'] and report['cost_usd'] is None
    assert len(report['effective_settings']) == len(report['trace']) == 3
    checked = subprocess.run([sys.executable, '-c', '''
import json, sys
from exercises.fixed.schemas.validate import validate, summarize_trace
report = json.load(sys.stdin)
for event in report['trace']:
    validate('trace-event', event)
def summarize(run_id):
    events = [e for e in report['trace'] if e['run_id'] == run_id]
    # The later launcher owns run_end. Supply its envelope for aggregate validation.
    events.append(dict(schema_version='1.0', type='run_end', run_id=run_id, event_id='end',
                       sequence=len(events), elapsed_ms=events[-1]['elapsed_ms'],
                       stop_reason='completed' if run_id == 'smoke' else 'service_error',
                       intervention=False))
    return summarize_trace(events, run_id)
summary = summarize('smoke')
assert summary['model_attempts'] == 2 and summary['total_tokens'] == 240
assert summary['usage']['input_tokens'] == 200
assert summary['usage']['cache_read_tokens'] == 20
assert summary['usage']['reasoning_tokens'] == 4
timeout = summarize('timeout')
assert timeout['total_tokens'] is None and timeout['usage']['input_tokens'] is None
print('contract-valid: 2 tool/continuation calls, 240 known tokens; timeout usage unknown')
'''], cwd=SESSION, input=json.dumps(report), capture_output=True, text=True, timeout=30)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    print(checked.stdout)


def test_invalid_configuration_and_missing_opt_in_exit_without_requests():
    invalid = subprocess.run([sys.executable, str(ROOT / 'setup/session-02-research-agents.py'),
                              '--adapter-smoke', '--invalid'],
                             cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert invalid.returncode == 2
    diagnosis = invalid.stdout + invalid.stderr
    assert 'Responses protocol' in diagnosis and 'requests sent: 0' in diagnosis
    opt_in = subprocess.run([sys.executable, str(ROOT / 'setup/session-02-research-agents.py'),
                             '--adapter-smoke'], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert opt_in.returncode == 2 and '--offline' in opt_in.stderr and '--live' in opt_in.stderr
    print(diagnosis, opt_in.stderr)
