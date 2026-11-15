"""Probe: a requirement fix without regressing earlier cases is retained even if a later case still fails."""

import json
import subprocess
import sys
from pathlib import Path

SESSION = Path(__file__).resolve().parents[2]


def recommend(before, after):
    program = """
import json, sys
from exercises.fixed import evaluate
before, after = json.load(sys.stdin)
print(json.dumps(evaluate.recommend(before, after)))
"""
    result = subprocess.run([sys.executable, '-c', program], cwd=SESSION, input=json.dumps([before, after]),
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def quality(rates, tokens=100):
    return dict(status='complete', per_case={c: dict(pass_rate=r) for c, r in zip('ABC', rates)},
                successes=sum(rates), quality_gates_pass=all(r == 1 for r in rates), tokens_per_success=tokens,
                efficiency_status='available')


def test_stepwise_requirement_fix_is_retained():
    # Baseline passes A only; candidate fixes B, keeps A, C still fails (e.g. check_table not yet wired).
    result = recommend(quality([1, 0, 0]), quality([1, 1, 0], 200))
    assert result['choice'] == 'retain', result


def test_unchanged_failing_quality_is_not_retained_on_tokens():
    # Control: no case improves, only cheaper -> must not be retained.
    result = recommend(quality([1, 0, 0], 200), quality([1, 0, 0], 50))
    assert result['choice'] != 'retain', result
