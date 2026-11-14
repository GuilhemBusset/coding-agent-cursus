"""Validate supplied numeric assets, not student answers or model outputs.

Standard library only. Rows are one-based and half-open when cited, without header.
"""

import csv
import re
from decimal import Decimal
from pathlib import Path

COLUMNS = ('row_id', 'instance_id', 'run_id', 'pair_id', 'method', 'feasible', 'cost', 'experiment_id')


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(COLUMNS):
            raise ValueError('unexpected CSV columns')
        rows = list(reader)
    seen = set()
    identities = set()
    pair_keys: dict[str, tuple[str, str]] = {}
    for row in rows:
        if set(row) != set(COLUMNS) or any(not isinstance(v, str) or not v for v in row.values()):
            raise ValueError('missing or extra field')
        if not re.fullmatch(r'(?:V[0-9]+-)?EV-T01:R[0-9]{4}', row['row_id']):
            raise ValueError('malformed row identifier')
        if row['row_id'] in seen:
            raise ValueError('duplicate row identifier')
        seen.add(row['row_id'])
        identity = (row['instance_id'], row['run_id'], row['method'])
        if identity in identities:
            raise ValueError('ambiguous duplicate method in pair')
        identities.add(identity)
        key = (row['instance_id'], row['run_id'])
        if pair_keys.setdefault(row['pair_id'], key) != key:
            raise ValueError('pair identity does not match instance/run')
        if row['feasible'] not in ('true', 'false') or not re.fullmatch(r'[0-9]+', row['cost']):
            raise ValueError('invalid feasibility or integer cost')
    if len(set(pair_keys.values())) != len(pair_keys):
        raise ValueError('instance/run has multiple pair identifiers')
    return rows


def paired_result(rows: list[dict[str, str]], baseline: str, candidate: str) -> dict:
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault((row['instance_id'], row['run_id']), []).append(row)
    pairs = []
    for group in groups.values():
        if len(group) == 2 and {r['method'] for r in group} == {baseline, candidate} and all(r['feasible'] == 'true' for r in group):
            pairs.append({r['method']: r for r in group})
    if not pairs:
        raise ValueError('no feasible complete pairs')
    left = sum(int(p[baseline]['cost']) for p in pairs)
    right = sum(int(p[candidate]['cost']) for p in pairs)
    if left <= 0:
        raise ValueError('nonpositive baseline denominator')
    ratio = Decimal(left - right) / Decimal(left)
    return dict(baseline_total=left, candidate_total=right, pair_count=len(pairs),
                reduction_ratio=float(ratio), reduction_percent=float(100 * ratio),
                row_ids=[p[m]['row_id'] for p in pairs for m in (baseline, candidate)])


def within_tolerance(observed: str, expected: str, absolute: str, relative: str = '0') -> bool:
    """Inclusive absolute/relative rule; public percentage uses 0.01 pp, relative 0."""
    actual, target, atol, rtol = map(Decimal, (observed, expected, absolute, relative))
    return all(x.is_finite() for x in (actual, target, atol, rtol)) and atol >= 0 and rtol >= 0 and abs(actual - target) <= max(atol, rtol * abs(target))
