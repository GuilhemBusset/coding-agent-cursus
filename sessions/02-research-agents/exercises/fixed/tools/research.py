"""Fixed deterministic research operations; no answer keys, network, shell or expression evaluation."""

import re
from pathlib import Path
from typing import Any

from ..corpus.audit import COLUMNS, load_rows, paired_result
from .corpus import ID, MAX_ROWS, Corpus, ToolError, require

MAX_READ = 4096
MAX_QUERY = 256
MAX_HITS = 8
MAX_SNIPPET = 600
MAX_PAIRS = 100


def fields(args: dict, required: set[str], optional: set[str] | None = None) -> None:
    require(isinstance(args, dict) and required <= args.keys()
            and args.keys() <= required | (optional or set()), 'missing or unsupported arguments')


def integer(value: Any, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def span(sid: str, start: int, end: int) -> dict:
    return dict(source_id=sid, kind='passage', start=start, end=end)


class ResearchTools:
    def __init__(self, root: Path):
        self.corpus = Corpus(root)

    def read(self, args: dict) -> tuple[dict, dict, dict]:
        fields(args, {'source_id'}, {'start', 'end'})
        sid = args['source_id']
        self.corpus.source(sid)
        text = self.corpus.text(sid)
        require(('start' in args) == ('end' in args), 'start and end must be supplied together')
        start, end = args.get('start', 0), args.get('end', min(len(text), MAX_READ))
        require(integer(start, 0, len(text)) and integer(end, 1, len(text))
                and start < end and end - start <= MAX_READ, 'invalid or oversized source span')
        passages = self.corpus.passages(sid)
        data = dict(span=span(sid, start, end), text=text[start:end])
        return dict(source_id=sid, start=start, end=end), data, dict(
            truncated=start > 0 or end < len(text), source_length=len(text),
            passage_ids=[p['passage_id'] for p in passages if p['start'] < end and p['end'] > start])

    def search(self, args: dict) -> tuple[dict, list, dict]:
        fields(args, {'query'}, {'limit'})
        query, limit = args['query'], args.get('limit', 5)
        require(isinstance(query, str) and 0 < len(query) <= MAX_QUERY and bool(query.strip()), 'invalid query')
        require(integer(limit, 1, MAX_HITS), 'invalid hit limit')
        terms = set(re.findall(r'\w+', query.casefold()))
        require(bool(terms), 'query must contain words')
        hits = []
        for sid in sorted(self.corpus.sources):
            for p in self.corpus.passages(sid):
                text = p['quote']
                score = len(terms & set(re.findall(r'\w+', text.casefold())))
                if score:
                    # Center a bounded snippet on the first matching word, preserving code-point offsets.
                    first = next(m.start() for m in re.finditer(r'\w+', text) if m.group().casefold() in terms)
                    offset = max(0, min(first - 80, len(text) - MAX_SNIPPET))
                    snippet = text[offset:offset + MAX_SNIPPET]
                    hits.append((score, sid, p['start'], dict(span=span(sid, p['start'] + offset,
                                p['start'] + offset + len(snippet)), text=snippet),
                                 dict(passage_id=p['passage_id'], passage_span=span(sid, p['start'], p['end']),
                                      score=score, truncated=len(snippet) < len(text))))
        hits.sort(key=lambda h: (-h[0], h[1], h[2]))
        return dict(query=query, limit=limit), [h[3] for h in hits[:limit]], dict(
            truncated=len(hits) > limit or any(h[4]['truncated'] for h in hits[:limit]),
            total_hits=len(hits), hits=[h[4] for h in hits[:limit]])

    def check_table(self, args: dict) -> tuple[dict, dict, dict]:
        fields(args, {'source_id', 'method_left', 'method_right', 'metric', 'unit', 'feasible_only', 'pair_key', 'pair_ids'})
        sid = args['source_id']
        source = self.corpus.source(sid)
        require(self.corpus.paths[sid].suffix == '.csv', 'source is not a cost table')
        require(args['metric'] == 'cost' and args['unit'] == source['units']['cost']
                and args['pair_key'] == 'pair_id' and args['feasible_only'] is True,
                'unsupported calculation; use feasible paired cost reduction')
        require(all(isinstance(args[k], str) and ID.fullmatch(args[k]) is not None
                    for k in ('method_left', 'method_right'))
                and args['method_left'] != args['method_right'], 'invalid methods')
        ids = args['pair_ids']
        require(isinstance(ids, list) and 0 < len(ids) <= MAX_PAIRS
                and all(isinstance(x, str) and ID.fullmatch(x) is not None for x in ids)
                and len(set(ids)) == len(ids), 'invalid pair IDs')
        # Validate path and byte size before the existing CSV validator opens it.
        self.corpus.text(sid)
        rows = load_rows(self.corpus.paths[sid])
        require({args['method_left'], args['method_right']} <= {r['method'] for r in rows}, 'unknown methods')
        require(len(rows) <= MAX_ROWS and source['row_ids'] == [r['row_id'] for r in rows], 'invalid row inventory')
        require(set(ids) <= {r['pair_id'] for r in rows}, 'unknown pair ID')
        selected = [r for r in rows if r['pair_id'] in ids]
        calculation = paired_result(selected, args['method_left'], args['method_right'])
        included = set(calculation['row_ids'])
        positions = {r['row_id']: i for i, r in enumerate(rows, 1)}
        groups: dict[str, dict[str, dict[str, str]]] = {}
        for row in selected:
            if row['row_id'] in included:
                groups.setdefault(row['pair_id'], {})[row['method']] = row
        pairs, audit_pairs, evidence = [], [], []
        for pid, group in sorted(groups.items()):
            left, right = group[args['method_left']], group[args['method_right']]
            pairs.append(dict(pair_id=pid, left_row=positions[left['row_id']], right_row=positions[right['row_id']],
                              left_value=int(left['cost']), right_value=int(right['cost']), feasible=True,
                              experiment_id=left['experiment_id']))
            audit_pairs.append(dict(pair_id=pid, left_row_id=left['row_id'], right_row_id=right['row_id'],
                                    left_experiment_id=left['experiment_id'], right_experiment_id=right['experiment_id'],
                                    instance_id=left['instance_id'], run_id=left['run_id']))
            for row in (left, right):
                evidence.append(dict(source_id=sid, kind='rows', start=positions[row['row_id']],
                                     end=positions[row['row_id']] + 1, columns=list(COLUMNS)))
        excluded = [r for r in rows if r['row_id'] not in included]
        data = {k: args[k] for k in ('source_id', 'method_left', 'method_right', 'metric', 'unit')}
        data.update(pairs=pairs, excluded_rows=[positions[r['row_id']] for r in excluded],
                    left_mean=calculation['baseline_total'] / len(pairs),
                    right_mean=calculation['candidate_total'] / len(pairs),
                    relative_reduction=calculation['reduction_ratio'], evidence=evidence)
        return args, data, dict(truncated=False, pairs=audit_pairs,
            excluded_row_ids=[r['row_id'] for r in excluded],
            excluded_reasons={r['row_id']: ('not_requested' if r['pair_id'] not in ids else 'incomplete_or_infeasible') for r in excluded},
            baseline_total=calculation['baseline_total'], candidate_total=calculation['candidate_total'],
            denominator=calculation['baseline_total'], reduction_percent=calculation['reduction_percent'],
            formula='(sum_left - sum_right) / sum_left', percentage_formula='100 * relative_reduction', unit=args['unit'])

    def invoke(self, tool: str, args: dict, run_id: str = 'offline', tool_call_id: str = 'call-1') -> dict:
        require(tool in ('read', 'search', 'check_table'), 'unknown tool')
        require(all(isinstance(x, str) and ID.fullmatch(x) is not None for x in (run_id, tool_call_id)), 'invalid call identity')
        result: dict[str, Any] = dict(schema_version='1.0', run_id=run_id, tool_call_id=tool_call_id, tool=tool)
        invocation = dict(result, arguments=args)
        try:
            normalized, data, audit = getattr(self, tool)(args)
            invocation['arguments'] = normalized
            result.update(status='ok', data=data, error=None)
        except (ValueError, TypeError, KeyError, OSError) as error:
            code = error.code if isinstance(error, ToolError) else 'invalid_input'
            result.update(status='error', data=None, error=dict(code=code, retryable=False))
            audit = dict(message=str(error) if isinstance(error, ValueError) else 'invalid or unavailable evidence')
        return dict(bridge_version='1.0', invocation=invocation, result=result, audit=audit)
