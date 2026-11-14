"""Generate visible seeded task bundles; never run a model or grade its answer.

Run from the session: uv run --locked python -m exercises.fixed.corpus.variants
The optional --out directory receives cases/<name>/variants/<variant-id>/.
"""

import argparse
import csv
import json
import random
import re
from pathlib import Path
from typing import Any

from .audit import COLUMNS, load_rows, paired_result

EXERCISES = Path(__file__).resolve().parents[2]
CASES = {'A': 'a-find', 'B': 'b-compare', 'C': 'c-audit'}
SEEDS = {'A': 20261115, 'B': 20261125, 'C': 20261135}


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def worksheet(rows: list[dict[str, str]], result: dict, baseline: str, candidate: str) -> str:
    included = set(result['row_ids'])
    lines = ['# Independent-check worksheet inputs and generated arithmetic', '',
             'All costs are fictional cost units. Pair on identical instance/run; exactly one row',
             'per method, both feasible. This file is checked independently in the offline tests.', '',
             '| Row | Instance / run | Method | Feasible | Cost | Included |',
             '| --- | --- | --- | --- | --- | --- |']
    for row in rows:
        lines.append(f"| {row['row_id']} | {row['instance_id']} / {row['run_id']} | {row['method']} | {row['feasible']} | {row['cost']} | {row['row_id'] in included} |")
    a, b, n = result['baseline_total'], result['candidate_total'], result['pair_count']
    lines.extend(['', f'Baseline {baseline}: {a}; candidate {candidate}: {b}; pairs: {n}.',
                  f'Paired means: {a / n:g} and {b / n:g} fictional cost units.',
                  f'Reduction ratio = ({a} - {b}) / {a} = {result["reduction_ratio"]:g} (ratio).',
                  f'Reduction percent = 100 * ({a} - {b}) / {a} = {result["reduction_percent"]:g} (percent).',
                  'Tolerance: 0.01 percentage points inclusive, relative 0; ratio tolerance 0.0001.',
                  'The denominator is the included baseline total. Do not average pair percentages.',
                  'No uncertain-demand experiment exists: general superiority remains unknown.', ''])
    return '\n'.join(lines)


def generate(case_id: str, seed: int, out: Path) -> Path:
    """Write a complete replacement case bundle; base files are inputs, not outputs."""
    name = CASES[case_id]
    base = EXERCISES / 'cases' / name
    variant_id = f'public-seed-{seed}'
    prefix = f'V{seed}-'
    target = out / 'cases' / name / 'variants' / variant_id
    rng = random.Random(seed)
    data = {k: read(base / f'{k}.json') for k in ('case', 'corpus', 'reference', 'examples')}
    corpus = data['corpus']
    mappings: dict[str, dict[str, str]] = {}
    mappings['sources'] = {s['source_id']: prefix + s['source_id'] for s in corpus['sources']}
    mappings['passages'] = {p['passage_id']: prefix + p['passage_id'] for s in corpus['sources'] for p in s['passages']}
    mappings['experiments'] = {e['experiment_id']: prefix + e['experiment_id'] for e in corpus['experiments']}
    mappings['families'] = {e['family_id']: prefix + e['family_id'] for e in corpus['experiments']}
    mappings['rows'] = {}
    mappings['pairs'] = {}
    if case_id == 'C':
        original_rows = load_rows(base / 'sources/EV-T01.csv')
        mappings['rows'] = {r['row_id']: prefix + r['row_id'] for r in original_rows}
        mappings['pairs'] = {r['pair_id']: prefix + r['pair_id'] for r in original_rows}
    adjective = rng.choice(['Cedar', 'Juniper', 'Willow', 'Birch'])
    harbor = rng.choice(['Harbor', 'Estuary', 'Delta', 'Canal'])
    mappings['methods'] = ({'audit-a': f'{adjective.lower()}-baseline', 'audit-b': f'{harbor.lower()}-candidate',
                            'method A': f'{adjective} Baseline', 'method B': f'{harbor} Candidate'} if case_id == 'C' else
                           {'Slot Ledger Private': f'{adjective} Ledger Private', 'Slot Ledger': f'{adjective} Ledger',
                            'Private Ledger': f'{adjective} Ledger Private', 'Queue Repair': f'{harbor} Repair',
                            'slot-ledger': f'{adjective.lower()}-ledger', 'queue-repair': f'{harbor.lower()}-repair',
                            'private-ledger': f'{adjective.lower()}-private'})
    replacements = {k: v for group in mappings.values() for k, v in group.items()}
    pattern = re.compile('|'.join(re.escape(k) for k in sorted(replacements, key=len, reverse=True)))
    timings = {48: rng.randint(43, 47), 84: rng.choice([n for n in range(75, 97) if n != 84]), 42: rng.randint(31, 41),
               55: rng.randint(51, 59), 8: rng.randint(9, 15)}
    scale, delta = rng.randint(2, 5), rng.randint(1, 5)
    percent = 20 + delta

    def text(value: str) -> str:
        value = pattern.sub(lambda m: replacements[m.group()], value)
        if case_id != 'C':
            # Change measured timings (including "42 and 55 seconds"), not P01's
            # 48 half-hour slots or other quantities that happen to share a value.
            value = re.sub(r'\b(48|84|42|55|8)(?=(?: and \d+)?[ -](?:seconds?\b|s\b))',
                           lambda m: str(timings[int(m.group())]), value)
        else:
            value = value.replace('20%', f'{percent}%')
        return value

    def transform(value: Any) -> Any:
        if isinstance(value, str):
            return text(value)
        if isinstance(value, list):
            return [transform(v) for v in value]
        if isinstance(value, dict):
            return {k: transform(v) for k, v in value.items()}
        return value

    changed = transform(data)
    changed['case']['variant_id'] = variant_id
    changed['reference']['variant_id'] = variant_id
    changed['case']['corpus_id'] = changed['corpus']['corpus_id'] = f'ev-dossier-v1.{variant_id}'
    for group in changed['examples'].values():
        for example in group:
            example['value']['variant_id'] = variant_id
    # Rebuild every quotation offset and relocate all references/examples to it.
    spans = {}
    for old, new in zip(corpus['sources'], changed['corpus']['sources'], strict=True):
        source_text = text((base / old['path']).read_text(encoding='utf-8'))
        for prior, passage in zip(old['passages'], new['passages'], strict=True):
            start = source_text.index(passage['quote'])
            passage.update(start=start, end=start + len(passage['quote']))
            spans[(new['source_id'], prior['start'], prior['end'])] = (passage['start'], passage['end'])
        if old['path'].endswith('.md'):
            dest = target / new['path']
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(source_text, encoding='utf-8', newline='\n')

    result = None
    if case_id == 'C':
        rows = transform(original_rows)
        costs = [100 * scale, (90 - delta) * scale, 200 * scale, (150 - 2 * delta) * scale,
                 300 * scale, scale, 500 * scale, 2 * scale]
        for row, cost in zip(rows, costs, strict=True):
            row['cost'] = str(cost)
        csv_path = target / f'sources/{prefix}EV-T01.csv'
        with csv_path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
        baseline, candidate = mappings['methods']['audit-a'], mappings['methods']['audit-b']
        result = paired_result(load_rows(csv_path), baseline, candidate)
        (target / 'worksheet.md').write_text(worksheet(rows, result, baseline, candidate), encoding='utf-8', newline='\n')

    def relocate(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                relocate(item)
        elif isinstance(value, dict):
            if value.get('kind') == 'passage':
                value['start'], value['end'] = spans[(value['source_id'], value['start'], value['end'])]
            if value.get('type') == 'number' and 'predicate' in value:
                if case_id != 'C' and value['unit'] == 'seconds':
                    value['value'] = timings[value['value']]
                elif result is not None and value['predicate'] in result:
                    value['value'] = result[value['predicate']]
            for item in value.values():
                relocate(item)
    relocate(changed['reference'])
    relocate(changed['examples'])
    ordered = changed['corpus']['sources']
    rng.shuffle(ordered)
    if [s['source_id'] for s in ordered] == list(mappings['sources'].values()):
        ordered.append(ordered.pop(0))
    for key, value in changed.items():
        write(target / f'{key}.json', value)
    if case_id == 'C':
        # Keep the full public rubric; substitute the generated worksheet for base arithmetic.
        assert result is not None
        original_readme = (base / 'README.md').read_text(encoding='utf-8')
        rubric = original_readme.split('## Evidence and public rubric')[1].split('## Public class')[0]
        rubric = text(rubric)
        readme = f'# C — {variant_id}\n\nRead case.json, corpus.json, sources/, reference.json and examples.json locally.\n\n'
        readme += (target / 'worksheet.md').read_text(encoding='utf-8')
        readme += '\n## Evidence and public rubric\n' + rubric
        # Example prose totals must match the changed table, including deliberate negatives.
        for group in changed['examples'].values():
            for example in group:
                example['prose'] = example['prose'].replace('300', str(result['baseline_total'])).replace('240', str(result['candidate_total']))
        write(target / 'examples.json', changed['examples'])
    else:
        readme = text((base / 'README.md').read_text(encoding='utf-8').split('## Public seeded variant')[0])
    (target / 'README.md').write_text(readme, encoding='utf-8', newline='\n')
    provenance = dict(schema_version='1.0',case_id=case_id,variant_id=variant_id,seed=seed,
                      base_revision='issue-181 A/B v1; issue-182 C v1',
                      base_path=f'cases/{name}',mappings=mappings,
                      source_order=[s['source_id'] for s in ordered],
                      numeric_transformation=({'timings_seconds': {str(k): v for k, v in timings.items()}} if case_id != 'C' else
                                              {'scale': scale, 'extra_reduction_percentage_points': delta}),
                      packaging='Self-contained case overlay: install this directory at cases/' + name + '; reference_path remains the canonical overlay path.',
                      independent_check='tests/labs/test_case_c_variants.py recomputes from sources, not these values')
    write(target / 'provenance.json', provenance)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=EXERCISES)
    args = parser.parse_args()
    for case_id, seed in SEEDS.items():
        print(generate(case_id, seed, args.out))


if __name__ == '__main__':
    main()
