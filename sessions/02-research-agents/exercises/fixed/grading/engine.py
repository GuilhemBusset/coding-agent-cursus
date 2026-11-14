"""Deterministic typed assertions and conservative evidence checks; no model calls."""

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from ..corpus.audit import within_tolerance
from ..schemas import validate as contracts

Json = dict[str, Any]
ANCHOR = re.compile(r'<a id="(claim-[A-Za-z0-9_.-]+)"></a>')


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def same_assertion(actual: Json, expected: Json) -> bool:
    """Reference tolerances only; exact subject/predicate/type/unit, unordered sets."""
    if any(actual[k] != expected[k] for k in ('subject', 'predicate', 'type', 'unit')):
        return False
    if expected['type'] == 'number':
        tolerance = expected['tolerance']
        return within_tolerance(str(actual['value']), str(expected['value']),
                                str(tolerance['absolute']), str(tolerance['relative']))
    if expected['type'] == 'string_set':
        return set(actual['value']) == set(expected['value'])
    return type(actual['value']) is type(expected['value']) and actual['value'] == expected['value']


class Corpus:
    """Resolve only local corpus IDs, with normalized text and real CSV bounds."""

    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.manifest = read(directory / 'corpus.json')
        self.sources = {s['source_id']: s for s in self.manifest['sources']}
        self.contents: dict[str, Any] = {}
        for sid, source in self.sources.items():
            path = (directory / source['path']).resolve()
            contracts.require(path.is_relative_to(self.directory), 'source outside case')
            if path.suffix == '.csv':
                with path.open(encoding='utf-8', newline='') as stream:
                    self.contents[sid] = list(csv.DictReader(stream))
            else:
                self.contents[sid] = unicodedata.normalize('NFC', path.read_text(encoding='utf-8'))
                for passage in source['passages']:
                    contracts.require(self.contents[sid][passage['start']:passage['end']] == passage['quote'],
                                      'corpus passage does not match source')

    def resolve(self, span: Json) -> Json:
        sid, start, end = span['source_id'], span['start'], span['end']
        contracts.require(sid in self.contents, 'unknown source')
        content = self.contents[sid]
        if span['kind'] == 'passage':
            contracts.require(isinstance(content, str) and 0 <= start < end <= len(content), 'passage bounds/kind')
            excerpt: Any = content[start:end]
        else:
            contracts.require(isinstance(content, list) and 1 <= start < end <= len(content) + 1, 'row bounds/kind')
            contracts.require(all(set(span['columns']) <= row.keys() for row in content), 'unknown CSV columns')
            excerpt = [{key: row[key] for key in span['columns']} for row in content[start - 1:end - 1]]
        return dict(span=span, source_path=str((self.directory / self.sources[sid]['path']).resolve()), excerpt=excerpt)

    def supports(self, cited: list[Json], accepted: list[Json]) -> bool:
        """All citations must be relevant; rows may split a complete accepted range.

        Passage alternatives are OR. Row spans jointly cover ALL accepted row/cell
        ranges. Narrow passage spans pass only if trimmed content is unchanged.
        This intentionally declines arbitrary semantic subspan entailment.
        """
        if not cited or not accepted:
            return False
        for span in cited + accepted:
            self.resolve(span)
        relevant = []
        for span in cited:
            matches = []
            for target in accepted:
                if (span['source_id'], span['kind']) != (target['source_id'], target['kind']):
                    continue
                if not target['start'] <= span['start'] < span['end'] <= target['end']:
                    continue
                if span['kind'] == 'passage':
                    # Equality of actual source content, never containment alone.
                    matches.append(self.resolve(span)['excerpt'].strip() == self.resolve(target)['excerpt'].strip())
                else:
                    matches.append(set(span['columns']) <= set(target['columns']))
            relevant.append(any(matches))
        if not all(relevant):
            return False
        rows = [s for s in accepted if s['kind'] == 'rows']
        if rows:
            needed = {(s['source_id'], row, col) for s in rows for row in range(s['start'], s['end']) for col in s['columns']}
            supplied = {(s['source_id'], row, col) for s in cited if s['kind'] == 'rows'
                        for row in range(s['start'], s['end']) for col in s['columns']}
            return needed <= supplied
        return True


def uncertainty_matches(claim: Json, requirement: Json) -> bool:
    assertion = claim['assertion']
    return (claim['kind'] == 'uncertainty' and claim['support_status'] == 'unknown' and
            not claim['evidence'] and assertion['type'] == 'string' and
            assertion['value'] in ('not-established', 'unknown', requirement['reason']) and
            all(assertion[k] == requirement[k] for k in ('subject', 'predicate')))


def evaluate(reference: Json, claims: list[Json], corpus: Corpus, output_errors: list[str]) -> tuple[list[Json], list[Json]]:
    """Return v1 assertions and companion claim diagnostics. IDs award no credit."""
    facts = reference['facts']
    checks: list[Json] = []
    details: list[Json] = []

    def add(category: str, target: str, passed: bool) -> None:
        checks.append(dict(assertion_id=f'{category}.{target}', category=category, target_ids=[target], passed=passed))

    typed: dict[str, list[Json]] = {}
    supported: dict[str, set[str]] = {f['fact_id']: set() for f in facts}
    for claim in claims:
        cid = claim['claim_id']
        matches = [f for f in facts if claim['kind'] != 'uncertainty' and same_assertion(claim['assertion'], f['assertion'])]
        typed[cid] = matches
        evidence = []
        errors = []
        for span in claim['evidence']:
            try:
                evidence.append(corpus.resolve(span))
            except (ValueError, KeyError) as exc:
                errors.append(str(exc))
        supported_facts = []
        for fact in matches:
            try:
                ok = claim['support_status'] == 'supported' and corpus.supports(claim['evidence'], fact['accepted_evidence'])
                # Claims cannot invent independent experiments or cite stale corrections.
                ok = ok and set(claim['experiment_ids']) == set(fact['experiment_ids'])
                for correction in reference['corrections']:
                    if fact['fact_id'] in correction['affected_fact_ids']:
                        sources = {s['source_id'] for s in claim['evidence']}
                        ok = ok and correction['source_id'] in sources and correction['supersedes_source_id'] not in sources
                if ok:
                    supported[fact['fact_id']].add(cid)
                    supported_facts.append(fact['fact_id'])
            except (ValueError, KeyError) as exc:
                errors.append(str(exc))
        if claim['kind'] == 'uncertainty' and not any(uncertainty_matches(claim, r) for r in reference['required_uncertainty']):
            output_errors.append(f'{cid}: uncertainty does not match a reference requirement')
        details.append(dict(claim_id=cid, assertion=claim['assertion'], kind=claim['kind'],
                            matched_fact_ids=[f['fact_id'] for f in matches], supported_fact_ids=supported_facts,
                            evidence=evidence, errors=errors))

    met: dict[str, bool] = {}
    for fact in facts:
        fid = fact['fact_id']
        if fact['evidence_policy'] == 'absence':
            # Public evaluator-owned absence contract: abstain without contradictory claims.
            expected = fact['assertion']
            related = [r for r in reference['required_uncertainty'] if r['subject'] == expected['subject']]
            met[fid] = bool(related) and any(uncertainty_matches(c, r) for c in claims for r in related) and not any(
                c['kind'] != 'uncertainty' and c['assertion']['subject'] == expected['subject'] and
                c['assertion']['predicate'] == expected['predicate'] and not same_assertion(c['assertion'], expected) for c in claims)
        else:
            # Correctness is independent of citations; count a required fact once.
            met[fid] = any(fact in matches for matches in typed.values())
        if fact['required']:
            add('required_fact', fid, met[fid])
        if fact['decisive']:
            add('decisive', fid, met[fid])

    for claim, detail in zip(claims, details):
        category = {'factual': 'citation', 'decision': 'decision'}.get(claim['kind'])
        if category:
            ok = bool(detail['supported_fact_ids'])
            if category == 'decision':
                # A supported conclusion must also have supported decisive premises.
                own = set(detail['supported_fact_ids'])
                ok = ok and all(bool(supported[f['fact_id']]) or f['fact_id'] in own
                                for f in facts if f['decisive'] and f['evidence_policy'] != 'absence')
            add(category, claim['claim_id'], ok)
    for requirement in reference['required_uncertainty']:
        add('uncertainty', requirement['requirement_id'], any(uncertainty_matches(c, requirement) for c in claims))
    add('output', reference['case_id'], not output_errors)
    for category in ('decisive', 'citation', 'decision', 'uncertainty'):
        if not any(c['category'] == category for c in checks):
            add(category, reference['case_id'], True)
    return checks, details


def grade_run(run: Path, case_directory: Path, policy_path: Path) -> Json:
    """Grade only after validating the saved config and terminal trace.

    Writes only evaluator outputs; preserves every research artifact. Bundle/hash
    verification beyond the supplied policy is the downstream launcher's job.
    """
    config = read(run / 'config.json')
    contracts.validate('run-config', config)
    events = [json.loads(line) for line in (run / 'trace.jsonl').read_text(encoding='utf-8').splitlines()]
    accounting = contracts.summarize_trace(events, config['run_id'])
    policy = read(policy_path)
    contracts.validate('policy', policy)
    contracts.require(hashlib.sha256(policy_path.read_bytes()).hexdigest() == config['policy_sha256'], 'policy hash mismatch')
    contracts.require(config['budgets'] == policy['budgets'], 'policy/config budgets mismatch')
    # This is deliberately the first reference read, after a validated run_end.
    case = read(case_directory / 'case.json')
    contracts.validate('case', case)
    reference = read(case_directory / 'reference.json')
    contracts.validate('reference', reference)
    contracts.require(all((a['case_id'], a['variant_id']) == (config['case_id'], config['variant_id'])
                          for a in (case, reference)), 'case/variant identity mismatch')
    corpus = Corpus(case_directory)
    contracts.require(corpus.manifest['corpus_id'] == case['corpus_id'], 'corpus identity mismatch')
    for fact in reference['facts']:
        for span in fact['accepted_evidence']:
            corpus.resolve(span)
    errors: list[str] = []
    claims: list[Json] = []
    report: Json = {}
    markdown = ''
    try:
        document = read(run / 'claims.json')
        contracts.validate('claims', document)
        claims = document['claims']
        report = read(run / 'report.json')
        contracts.validate('report', report)
        for artifact in (document, report):
            contracts.require(all(artifact[k] == config[k] for k in ('run_id', 'case_id', 'variant_id')), 'output identity mismatch')
        markdown = (run / 'report.md').read_text(encoding='utf-8')
        anchors = ANCHOR.findall(markdown)
        contracts.require(bool(markdown.strip()), 'empty report')
        contracts.require({a['claim_id'] for a in report['claim_anchors']} == {c['claim_id'] for c in claims}, 'report claim coverage')
        contracts.require(len(anchors) == len(set(anchors)) and set(anchors) == {a['anchor'] for a in report['claim_anchors']}, 'report anchor mismatch')
        # Every anchor needs prose; peers decide whether that prose is true.
        contracts.require(all(part.strip() for part in ANCHOR.split(markdown)[2::2]), 'empty anchored prose')
    except (ValueError, OSError, KeyError) as exc:
        errors.append(str(exc))
        report = {}
    checks, details = evaluate(reference, claims, corpus, errors)
    passed = lambda category: all(c['passed'] for c in checks if c['category'] == category)
    required = [c for c in checks if c['category'] == 'required_fact']
    contracts.require(bool(required), 'reference has no required facts')
    coverage = sum(c['passed'] for c in required) / len(required)
    score = {k: config[k] for k in ('schema_version', 'run_id', 'case_id', 'variant_id', 'hashes', 'policy_sha256', 'evidence_kind')}
    score.update(accounting)
    score.update(grading_assertions=checks, failed_assertion_ids=[c['assertion_id'] for c in checks if not c['passed']],
                 required_facts_total=len(required), required_facts_met=sum(c['passed'] for c in required),
                 required_fact_coverage=coverage, decisive_pass=passed('decisive'), all_factual_spans_valid=passed('citation'),
                 no_unsupported_decision=passed('decision'), uncertainty_pass=passed('uncertainty'),
                 output_valid=passed('output'), peer_review='pending')
    score['quality_pass'] = all(passed(k) for k in ('decisive', 'citation', 'decision', 'uncertainty', 'output')) and coverage >= max(0.8, policy['gates']['required_fact_fraction']) and not accounting['intervention']
    contracts.validate('scorecard', score)
    budgets = {}
    for field, limit in config['budgets'].items():
        value = accounting[field]
        budgets[field] = dict(observed=value, limit=limit, status='unknown' if value is None else 'exceeded' if value > limit else 'within')
    diagnostics = dict(machine_check='pass' if score['quality_pass'] else 'fail', peer_review='pending',
                       output_errors=errors, claims=details, budgets=budgets,
                       autonomy=dict(intervention=accounting['intervention']), coverage_threshold=max(0.8, policy['gates']['required_fact_fraction']),
                       provisional=policy['provisional'], calibration=policy['calibration'])
    for name, value in [('scorecard.json', score), ('grading.json', diagnostics)]:
        (run / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    write_checklist(run, report, markdown, details)
    return score


def write_checklist(run: Path, report: Json, markdown: str, details: list[Json]) -> None:
    lines = ['# Peer prose review — pending', '',
             'Machine results are in [scorecard.json](scorecard.json) and [grading.json](grading.json).',
             'Matching typed assertions and accepted evidence is not semantic entailment of prose.', '',
             '- [ ] Read the ENTIRE [report](report.md), including text before/between/after anchors.',
             '- [ ] Identify every factual or decision assertion absent from [claims.json](claims.json); request revision.',
             '- [ ] Check qualifications, corrected premises, independence and missing-evidence explanations.',
             '- [ ] Record a separate peer verdict; machine pass leaves peer review pending.', '']
    anchors = {a['claim_id']: a['anchor'] for a in report.get('claim_anchors', [])}
    for detail in details:
        cid = detail['claim_id']
        anchor = anchors.get(cid)
        lines += [f'## {cid}', '', f'- [ ] Audit [report sentence](report.md#{anchor}) against [typed claim](claims.json) `{cid}`.',
                  f"Typed assertion: `{json.dumps(detail['assertion'], ensure_ascii=False)}`", '',
                  f"Matched facts: {detail['matched_fact_ids']}; supported facts: {detail['supported_fact_ids']}.", '']
        if anchor:
            match = re.search(re.escape(f'<a id="{anchor}"></a>') + r'(.*?)(?=<a id="claim-|\Z)', markdown, re.S)
            if match:
                lines += ['Report text:', '', match.group(1).strip(), '']
        for resolved in detail['evidence']:
            path = Path(resolved['source_path'])
            # Absolute file URI remains usable when run/corpus are on different drives.
            lines += [f"Evidence [source]({path.as_uri()}) — `{json.dumps(resolved['span'])}`", '',
                      '```json', json.dumps(resolved['excerpt'], ensure_ascii=False, indent=2), '```', '']
        lines += ['- [ ] Does the cited excerpt support the actual prose, without added scope or claims?', '']
    (run / 'peer-review.md').write_text('\n'.join(lines), encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--case', type=Path, required=True, help='public case directory (base or variant)')
    parser.add_argument('--policy', type=Path, required=True)
    args = parser.parse_args()
    try:
        score = grade_run(args.run, args.case, args.policy)
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps(dict(error=str(exc), machine_check='invalid_run')))
        return 2
    print(json.dumps(dict(quality_pass=score['quality_pass'], peer_review=score['peer_review'],
                          failed_assertion_ids=score['failed_assertion_ids'])))
    return 0 if score['quality_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
