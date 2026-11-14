"""Offline v1 contract checks; no inference, corpus lookup, or answer grading.

The JSON Schemas are the interchange contract. This small validator supports only
its declared vocabulary and rejects unsupported keywords rather than ignoring them.
Relationship checks validate consistency, never entailment or factual correctness.
"""

import json
import math
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
KEYWORDS = {
    '$schema', '$id', '$defs', '$ref', 'title', 'description', 'type', 'const', 'enum',
    'oneOf', 'properties', 'required', 'additionalProperties', 'items', 'minItems',
    'uniqueItems', 'minLength', 'pattern', 'minimum', 'maximum',
}
TOKEN_FIELDS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens')


class ContractError(ValueError):
    """An artifact violates a shape or relationship invariant."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def audit_schema(schema: dict[str, Any]) -> None:
    """Fail closed when the checked-in schemas grow beyond this vocabulary."""
    require(not (set(schema) - KEYWORDS), f'unsupported schema keywords: {set(schema) - KEYWORDS}')
    for key in ('$defs', 'properties'):
        for child in schema.get(key, {}).values():
            audit_schema(child)
    for child in schema.get('oneOf', []):
        audit_schema(child)
    if 'items' in schema:
        audit_schema(schema['items'])


def _resolve(reference: str, document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    filename, _, fragment = reference.partition('#')
    if filename:
        require(filename == Path(filename).name and filename.endswith('.v1.schema.json'), 'only local v1 references')
        document = load(ROOT / filename)
        audit_schema(document)
    target = document
    if fragment:
        require(fragment.startswith('/'), 'JSON pointer reference required')
        for part in fragment[1:].split('/'):
            target = target[part.replace('~1', '/').replace('~0', '~')]
    return target, document


def _shape(value: Any, schema: dict[str, Any], document: dict[str, Any], path: str) -> None:
    if '$ref' in schema:
        target, target_doc = _resolve(schema['$ref'], document)
        _shape(value, target, target_doc, path)
    if 'oneOf' in schema:
        failures = []
        matches = 0
        for branch in schema['oneOf']:
            try:
                _shape(value, branch, document, path)
                matches += 1
            except ContractError as exc:
                failures.append(str(exc))
        require(matches == 1, f'{path}: oneOf matched {matches}: {"; ".join(failures)}')
    if 'type' in schema:
        types = {
            'object': isinstance(value, dict), 'array': isinstance(value, list),
            'string': isinstance(value, str), 'null': value is None, 'boolean': isinstance(value, bool),
            'integer': isinstance(value, int) and not isinstance(value, bool),
            'number': isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
        }
        require(schema['type'] in types, f'unsupported type {schema["type"]}')
        require(types[schema['type']], f'{path}: type {schema["type"]}')
    if 'const' in schema:
        require(type(value) is type(schema['const']) and value == schema['const'] or
                isinstance(value, (int, float)) and not isinstance(value, bool) and
                isinstance(schema['const'], (int, float)) and not isinstance(schema['const'], bool) and
                value == schema['const'], f'{path}: const {schema["const"]}')
    if 'enum' in schema:
        require(value in schema['enum'], f'{path}: enum')
    if isinstance(value, dict):
        require(set(schema.get('required', [])) <= set(value), f'{path}: required fields missing')
        properties = schema.get('properties', {})
        if schema.get('additionalProperties') is False:
            require(set(value) <= set(properties), f'{path}: additionalProperties')
        for key, child in properties.items():
            if key in value:
                _shape(value[key], child, document, f'{path}.{key}')
    if isinstance(value, list):
        require(len(value) >= schema.get('minItems', 0), f'{path}: minItems')
        if schema.get('uniqueItems'):
            require(len({json.dumps(x, sort_keys=True) for x in value}) == len(value), f'{path}: uniqueItems')
        if 'items' in schema:
            for i, item in enumerate(value):
                _shape(item, schema['items'], document, f'{path}[{i}]')
    if isinstance(value, str):
        require(len(value) >= schema.get('minLength', 0), f'{path}: minLength')
        if 'pattern' in schema:
            require(re.search(schema['pattern'], value) is not None, f'{path}: pattern')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        require(math.isfinite(value), f'{path}: finite number required')
        if 'minimum' in schema:
            require(value >= schema['minimum'], f'{path}: minimum')
        if 'maximum' in schema:
            require(value <= schema['maximum'], f'{path}: maximum')


def validate_shape(kind: str, value: Any) -> None:
    schema = load(ROOT / f'{kind}.v1.schema.json')
    audit_schema(schema)
    _shape(value, schema, schema, '$')


def _usage(value: dict[str, Any]) -> None:
    counts = [value[key] for key in TOKEN_FIELDS]
    if value['status'] == 'complete':
        require(all(x is not None for x in counts), 'complete usage requires every count')
    elif value['status'] == 'unknown':
        require(all(x is None for x in counts), 'unknown usage requires null counts')
    else:
        require(any(x is None for x in counts) and any(x is not None for x in counts), 'partial usage needs known and unknown counts')
    if all(value[x] is not None for x in ('input_tokens', 'cache_read_tokens', 'cache_write_tokens')):
        require(value['cache_read_tokens'] + value['cache_write_tokens'] <= value['input_tokens'], 'cache subsets exceed input')
    if value['reasoning_tokens'] is not None and value['output_tokens'] is not None:
        require(value['reasoning_tokens'] <= value['output_tokens'], 'reasoning subset exceeds output')


def _walk(value: Any) -> None:
    if isinstance(value, dict):
        if value.get('kind') in ('passage', 'rows'):
            require(value['start'] < value['end'], 'span must be nonempty and ordered')
        if set(TOKEN_FIELDS) <= set(value):
            _usage(value)
        for child in value.values():
            _walk(child)
    elif isinstance(value, list):
        for child in value:
            _walk(child)


def unique(values: list[dict[str, Any]], key: str) -> set[str]:
    result = {v[key] for v in values}
    require(len(result) == len(values), f'duplicate {key}')
    return result


def validate(kind: str, value: dict[str, Any]) -> None:
    """Validate one artifact, including local cross-field invariants."""
    validate_shape(kind, value)
    _walk(value)
    if kind == 'reference':
        fact_ids = unique(value['facts'], 'fact_id')
        experiments = unique(value['experiments'], 'experiment_id')
        unique(value['required_uncertainty'], 'requirement_id')
        for fact in value['facts']:
            require(not fact['decisive'] or fact['required'], 'decisive facts must be required')
            require(bool(fact['accepted_evidence']) == (fact['evidence_policy'] == 'required'), 'accepted evidence policy mismatch')
            require(set(fact['experiment_ids']) <= experiments, 'unknown experiment identity')
            require(fact['fact_id'] not in fact['supersedes_fact_ids'], 'self supersession')
        for correction in value['corrections']:
            require(set(correction['affected_fact_ids']) <= fact_ids, 'correction fact identity')
            require(correction['source_id'] != correction['supersedes_source_id'], 'self correction')
    elif kind == 'claims':
        claim_ids = unique(value['claims'], 'claim_id')
        for claim in value['claims']:
            if claim['support_status'] == 'supported' and claim['kind'] in ('factual', 'decision'):
                require(bool(claim['evidence']), 'supported claim requires evidence')
            if claim['support_status'] == 'unknown':
                require(not claim['evidence'], 'unknown claim cannot assert supporting evidence')
            require(set(claim['supersedes_claim_ids']) <= claim_ids - {claim['claim_id']}, 'superseded claim identity')
    elif kind == 'report':
        unique(value['claim_anchors'], 'claim_id')
        unique(value['claim_anchors'], 'anchor')
    elif kind == 'tool-input' and value['tool'] == 'read':
        require(value['arguments']['start'] < value['arguments']['end'], 'read span order')
    elif kind == 'tool-result' and value['status'] == 'ok' and value['tool'] == 'check_table':
        data = value['data']
        unique(data['pairs'], 'pair_id')
        rows = [p[key] for p in data['pairs'] for key in ('left_row', 'right_row')]
        require(len(rows) == len(set(rows)), 'paired rows cannot be reused')
        require(not set(rows) & set(data['excluded_rows']), 'excluded rows cannot enter pairs')
    elif kind == 'run-config':
        require((value['evidence_kind'] == 'replay') == (value['replay_of'] is not None), 'replay identity')
        require(value['hashes']['rating_bundle'] == value['rating_bundle']['sha256'], 'bundle hash identity')
    elif kind == 'trace-event':
        if value['type'] == 'tool_invocation':
            for key in ('input', 'result'):
                validate('tool-' + key, value[key])
                require(all(value[key][field] == value[field] for field in ('run_id', 'tool_call_id')), 'tool identity mismatch')
            require(value['input']['tool'] == value['result']['tool'], 'tool identity mismatch')
        elif value['type'] == 'model_attempt':
            require((value['status'] == 'ok') == (value['error'] is None), 'attempt error/status mismatch')
    elif kind == 'scorecard':
        ids = unique(value['grading_assertions'], 'assertion_id')
        require(set(value['failed_assertion_ids']) <= ids, 'unknown grading assertion')
        require(set(value['failed_assertion_ids']) == {a['assertion_id'] for a in value['grading_assertions'] if not a['passed']}, 'failed assertion identity')
        require(value['required_facts_met'] <= value['required_facts_total'], 'fact counts')
        require(math.isclose(value['required_fact_coverage'], value['required_facts_met'] / value['required_facts_total']), 'coverage mismatch')
        tokens = value['usage']
        expected = None if tokens['input_tokens'] is None or tokens['output_tokens'] is None else tokens['input_tokens'] + tokens['output_tokens']
        require(value['total_tokens'] == expected, 'unknown totals cannot become zero or double count')
    elif kind == 'policy':
        for mode, trials in [('class', 1), ('submission', 3)]:
            schedule = value['schedule'][mode]
            require({(x['case_id'], x['trial']) for x in schedule} == {(c, t) for c in 'ABC' for t in range(1, trials + 1)} and len(schedule) == 3 * trials, 'trial schedule')
            for case in 'ABC':
                require(len({x['variant_id'] for x in schedule if x['case_id'] == case}) == 1, 'one announced variant per case')


def summarize_trace(events: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
    """Check trace identities and derive event accounting, including failed attempts."""
    require(bool(events), 'empty trace')
    unique(events, 'event_id')
    attempts: dict[str, dict[str, Any]] = {}
    tools: dict[str, dict[str, Any]] = {}
    requests: set[str] = set()
    last_time = 0
    intervened = False
    for index, event in enumerate(events):
        validate('trace-event', event)
        require(event['run_id'] == run_id and event['sequence'] == index, 'run/sequence identity mismatch')
        require(event['elapsed_ms'] >= last_time, 'elapsed time must be monotone')
        last_time = event['elapsed_ms']
        if event['type'] == 'model_attempt':
            require(event['attempt_id'] not in attempts, 'duplicate attempt identity')
            prior = event['retry_of']
            if event['request_id'] in requests:
                require(prior in attempts and attempts[prior]['request_id'] == event['request_id'], 'retry request identity')
                require(attempts[prior]['status'] != 'ok', 'cannot retry successful attempt')
            else:
                require(prior is None, 'first attempt cannot be retry')
            attempts[event['attempt_id']] = event
            requests.add(event['request_id'])
        elif event['type'] == 'tool_invocation':
            require(event['tool_call_id'] not in tools, 'duplicate tool identity')
            attempt = attempts.get(event['attempt_id'])
            require(attempt is not None and attempt['request_id'] == event['request_id'] and attempt['status'] == 'ok', 'tool request/attempt identity')
            if event['retry_of'] is not None:
                prior = tools.get(event['retry_of'])
                require(prior is not None and prior['result']['status'] == 'error' and
                        prior['input']['tool'] == event['input']['tool'] and prior['input']['arguments'] == event['input']['arguments'], 'tool retry identity')
            tools[event['tool_call_id']] = event
        elif event['type'] == 'intervention':
            intervened = True
        elif event['type'] == 'run_end':
            require(index == len(events) - 1, 'run_end must be last')
            require(event['intervention'] == intervened, 'intervention mismatch')
    require(events[-1]['type'] == 'run_end', 'missing run_end')
    usage: dict[str, Any] = {}
    for field in TOKEN_FIELDS:
        counts = [event['usage'][field] for event in attempts.values()]
        usage[field] = sum(counts) if all(x is not None for x in counts) else None
    usage['status'] = 'complete' if all(usage[k] is not None for k in TOKEN_FIELDS) else 'unknown' if all(usage[k] is None for k in TOKEN_FIELDS) else 'partial'
    total = None if usage['input_tokens'] is None or usage['output_tokens'] is None else usage['input_tokens'] + usage['output_tokens']
    return dict(model_attempts=len(attempts), logical_requests=len(requests), tool_invocations=len(tools),
                service_errors=sum(e['status'] != 'ok' for e in attempts.values()) + sum(e['result']['status'] == 'error' for e in tools.values()),
                usage=usage, total_tokens=total, elapsed_ms=last_time, intervention=intervened, stop_reason=events[-1]['stop_reason'])


def validate_run(case: dict[str, Any], reference: dict[str, Any], config: dict[str, Any], claims: dict[str, Any],
                 report: dict[str, Any], markdown: str, events: list[dict[str, Any]], scorecard: dict[str, Any]) -> None:
    """Check linked artifacts. Grading assertions are supplied by the later evaluator."""
    artifacts = dict(case=case, reference=reference, **{'run-config': config}, claims=claims, report=report, scorecard=scorecard)
    for kind, value in artifacts.items():
        validate(kind, value)
        require((value['case_id'], value['variant_id']) == (case['case_id'], case['variant_id']), 'case/variant identity mismatch')
        if 'run_id' in value:
            require(value['run_id'] == config['run_id'], 'run identity mismatch')
    facts = {f['fact_id'] for f in reference['facts']}
    experiments = {e['experiment_id'] for e in reference['experiments']}
    for claim in claims['claims']:
        require(set(claim['reference_fact_ids']) <= facts, 'reference fact identity mismatch')
        require(set(claim['experiment_ids']) <= experiments, 'experiment identity mismatch')
    ids = {cl['claim_id'] for cl in claims['claims']}
    require({a['claim_id'] for a in report['claim_anchors']} == ids, 'report claim identity mismatch')
    actual_anchors = re.findall(r'<a id="(claim-[A-Za-z0-9_.-]+)"></a>', markdown)
    require(len(actual_anchors) == len(set(actual_anchors)) and set(actual_anchors) == {a['anchor'] for a in report['claim_anchors']}, 'report anchor mismatch')
    accounting = summarize_trace(events, config['run_id'])
    for field, expected in accounting.items():
        require(scorecard[field] == expected, f'scorecard event mismatch: {field}')
    for field in ('hashes', 'policy_sha256', 'evidence_kind'):
        require(config[field] == scorecard[field], f'scorecard identity mismatch: {field}')
    assertions = scorecard['grading_assertions']
    required = {f['fact_id'] for f in reference['facts'] if f['required']}
    fact_checks = [a for a in assertions if a['category'] == 'required_fact']
    require(all(len(a['target_ids']) == 1 for a in fact_checks) and
            {a['target_ids'][0] for a in fact_checks} == required and len(fact_checks) == len(required), 'required fact assertion coverage')
    require(scorecard['required_facts_total'] == len(required) and scorecard['required_facts_met'] == sum(a['passed'] for a in fact_checks), 'required fact counts mismatch')
    categories = {
        'decisive': ({f['fact_id'] for f in reference['facts'] if f['decisive']}, 'decisive_pass'),
        'citation': ({c['claim_id'] for c in claims['claims'] if c['kind'] == 'factual'}, 'all_factual_spans_valid'),
        'decision': ({c['claim_id'] for c in claims['claims'] if c['kind'] == 'decision'}, 'no_unsupported_decision'),
        'uncertainty': ({r['requirement_id'] for r in reference['required_uncertainty']}, 'uncertainty_pass'),
        'output': ({case['case_id']}, 'output_valid'),
    }
    for category, (targets, field) in categories.items():
        checks = [a for a in assertions if a['category'] == category]
        require(bool(checks) and {t for a in checks for t in a['target_ids']} == (targets or {case['case_id']}), f'{category} assertion coverage')
        require(scorecard[field] == all(a['passed'] for a in checks), f'{field} assertion mismatch')
    if any(c['kind'] == 'factual' and c['support_status'] != 'supported' for c in claims['claims']):
        require(not scorecard['all_factual_spans_valid'], 'unsupported factual claim cannot pass citations')
    if any(c['kind'] == 'decision' and c['support_status'] != 'supported' for c in claims['claims']):
        require(not scorecard['no_unsupported_decision'], 'unsupported decision cannot pass')
    quality = (all(scorecard[f] for f in ('decisive_pass', 'all_factual_spans_valid', 'no_unsupported_decision', 'uncertainty_pass', 'output_valid'))
               and scorecard['required_fact_coverage'] >= 0.8 and not scorecard['intervention'])
    require(scorecard['quality_pass'] == quality, 'quality gate mismatch')


def summarize_scorecards(scores: list[dict[str, Any]]) -> dict[str, Any]:
    """All runs remain in aggregates. This does not compare or grade candidates."""
    require(bool(scores), 'no scorecards')
    for score in scores:
        validate('scorecard', score)
    unique(scores, 'run_id')
    successes = sum(score['quality_pass'] for score in scores)
    known = all(score['total_tokens'] is not None for score in scores)
    total = sum(score['total_tokens'] for score in scores) if known else None
    return dict(runs=len(scores), successes=successes, pass_rate=successes / len(scores), total_tokens=total,
                tokens_per_success=total / successes if known and successes else None,
                efficiency_status='zero_success' if not successes else 'unknown_usage' if not known else 'available')
