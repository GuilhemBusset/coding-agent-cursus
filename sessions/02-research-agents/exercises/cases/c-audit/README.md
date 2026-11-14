# C — Audit a measured saving and withhold an unsupported conclusion

[case.json](case.json) includes the question and a local P01 summary. All methods,
notes, runs and cost units are fictional teaching data. No solver, API, Session 1
folder or external literature is needed. Read [corpus.json](corpus.json), the
[protocol](sources/EV-S13.md), [demand boundary](sources/EV-S14.md) and
[CSV](sources/EV-T01.csv). The public [reference](reference.json),
[examples](examples.json) and worksheet below are available before building.

**Question:** Is method B 20% cheaper than method A on the feasible paired runs?
Does that establish superiority under uncertain demand?

## Hand-worked worksheet (base)

Pair by identical `instance_id` and `run_id`, with a single consistent `pair_id`.
Require exactly one `audit-a` and one `audit-b` row, both `feasible=true`.

| Pair | A row / cost | B row / cost | Include? |
| --- | --- | --- | --- |
| EV-PAIR-0001 | EV-T01:R0001 / 100 | EV-T01:R0002 / 90 | Yes |
| EV-PAIR-0002 | EV-T01:R0003 / 200 | EV-T01:R0004 / 150 | Yes |
| EV-PAIR-0003 | EV-T01:R0005 / 300 | EV-T01:R0006 / 1 | No: B infeasible |
| EV-PAIR-0004 | EV-T01:R0007 / 500 | absent | No: unpaired |
| EV-PAIR-0005 | absent | EV-T01:R0008 / 2 | No: unpaired |

Costs are exact integer **fictional cost units**. Included baseline A total is
100 + 200 = **300**; B total is 90 + 150 = **240**. The corresponding paired means
are 150 and 120. The denominator is A's included total, never all A rows or B's
cost. Reduction ratio = (300 − 240) / 300 = **0.2 (ratio)**. Percentage reduction
= 100 × 0.2 = **20 (percent)**. Thus the measured claim is supported *on these two
feasible deterministic pairs*. Equal-sized paired means give the same ratio.
The mean of the individual reductions, (10% + 25%) / 2 = 17.5%, answers a different
question and is not accepted for this aggregate claim.

Accept percentage error ≤ **0.01 percentage points**, relative tolerance zero,
inclusive at 19.99 and 20.01. The ratio tolerance is 0.0001 (ratio), not 0.01;
reporting 0.2 percent confuses units. Integer totals, membership and identities are
exact. The formula and filter are in EV-S13:P02–P03.

## Evidence and public rubric

All reference facts are required and decisive. Numeric equality alone never passes.
For computed facts, row evidence must jointly cover **every included pair** and
all columns establishing `row_id`, `instance_id`, `run_id`, `pair_id`, `method`,
`feasible`, `cost`, and `experiment_id`. The key's canonical rows span is
`EV-T01`, kind `rows`, start 1, end 5, with those columns: one-based half-open
**data** rows excluding the header. Equivalent individual row spans covering the
same rows/columns are acceptable; a source ID alone or a cost-only column is not.
Extra excluded rows cannot substitute for an included row. Protocol and limitation
claims require the corresponding entailing passages. Offsets refer to normalized
NFC text, LF newlines, zero-based half-open Unicode code points.

**The independent uncertainty requirement is decisive:** explicitly say there is
no uncertain-demand experiment in the dossier, so B's superiority under uncertain
demand remains unknown. Cite EV-S14:P01 for the dossier boundary. An `unknown`
uncertainty claim has no invented supporting evidence; the factual statement about
the dossier's boundary has its own passage evidence. A correct 20% with complete
row citations but a general-superiority claim fails. A correct 20% without row
evidence or without the missing-evidence qualification also fails. No wording is
prescribed: “these two known days favour B, but we cannot infer behaviour with
random arrivals because none were tested” expresses the same qualification.

Matched uncertain-demand scenarios and repeated demand samples would help answer
that separate question (EV-S14:P02). They have not been run. Absence of evidence
establishes neither superiority nor inferiority. The positive and negative typed
examples illustrate these distinctions; they are public assets, not a grader.

## Public class and submission variant

The [public manifest](../../fixed/config/public/manifest.json) announces C's
`public-seed-20261135` for class and for all three independent submission trials,
identically for baseline and candidate. Its [bundle](variants/public-seed-20261135/)
changes names, values and source order; use its own worksheet and citations.
See [generation instructions](../../fixed/corpus/README.md). Task generation is
deterministic; repeated model trials do not promise identical model outputs.
