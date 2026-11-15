"""A result the harness returns after a budget stop is retained and graded, not discarded."""

import json

from test_run_boundary import (  # fixtures are shared with the integration suites
    installed,
    lab,
    launch,
    load,
    response,
    snapshot,
)


def test_output_returned_after_budget_stop_is_retained(lab):
    fixtures = lab['cache'] / 'exercises/fixed/grading/fixtures/pass-A'
    output = dict(claims=load(fixtures / 'claims.json')['claims'],
                  claim_anchors=load(fixtures / 'report.json')['claim_anchors'],
                  markdown=(fixtures / 'report.md').read_text(encoding='utf-8'))
    # The harness stops on an exhausted budget and returns what it already has:
    # completion logic the issue leaves to the student harness.
    saved = snapshot(lab, 'const OUT = ' + json.dumps(output) + ''';
export async function run(api) {
  await api.model();
  try { await api.model(); } catch (error) { return OUT; }
  return OUT;
}''')
    options = dict(lab['options'], budgets=dict(lab['options']['budgets'], model_attempts=1))
    out, status = launch(lab, saved, [response(), response()], options=options)
    # The stop reason stays exact, and no further request was dispatched ...
    assert status['detail'] == status['stop_reason'] == 'model_budget'
    assert load(out / 'accounting.json')['model_attempts'] == 1
    # ... but the harness's returned result is a retained partial artifact.
    assert (out / 'candidate-output.json').is_file()
    assert load(out / 'claims.json')['claims'] == output['claims']
    assert 'No research result was produced' not in (out / 'report.md').read_text(encoding='utf-8')
