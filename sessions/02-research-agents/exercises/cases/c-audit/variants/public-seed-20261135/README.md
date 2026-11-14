# C — public-seed-20261135

Read case.json, corpus.json, sources/, reference.json and examples.json locally.

# Independent-check worksheet inputs and generated arithmetic

All costs are fictional cost units. Pair on identical instance/run; exactly one row
per method, both feasible. This file is checked independently in the offline tests.

| Row | Instance / run | Method | Feasible | Cost | Included |
| --- | --- | --- | --- | --- | --- |
| V20261135-EV-T01:R0001 | day-1 / run-1 | birch-baseline | true | 200 | True |
| V20261135-EV-T01:R0002 | day-1 / run-1 | estuary-candidate | true | 172 | True |
| V20261135-EV-T01:R0003 | day-2 / run-1 | birch-baseline | true | 400 | True |
| V20261135-EV-T01:R0004 | day-2 / run-1 | estuary-candidate | true | 284 | True |
| V20261135-EV-T01:R0005 | day-3 / run-1 | birch-baseline | true | 600 | False |
| V20261135-EV-T01:R0006 | day-3 / run-1 | estuary-candidate | false | 2 | False |
| V20261135-EV-T01:R0007 | day-4 / run-1 | birch-baseline | true | 1000 | False |
| V20261135-EV-T01:R0008 | day-5 / run-1 | estuary-candidate | true | 4 | False |

Baseline birch-baseline: 600; candidate estuary-candidate: 456; pairs: 2.
Paired means: 300 and 228 fictional cost units.
Reduction ratio = (600 - 456) / 600 = 0.24 (ratio).
Reduction percent = 100 * (600 - 456) / 600 = 24 (percent).
Tolerance: 0.01 percentage points inclusive, relative 0; ratio tolerance 0.0001.
The denominator is the included baseline total. Do not average pair percentages.
No uncertain-demand experiment exists: general superiority remains unknown.

## Evidence and public rubric


All reference facts are required and decisive. Numeric equality alone never passes.
For computed facts, row evidence must jointly cover **every included pair** and
all columns establishing `row_id`, `instance_id`, `run_id`, `pair_id`, `method`,
`feasible`, `cost`, and `experiment_id`. The key's canonical rows span is
`V20261135-EV-T01`, kind `rows`, start 1, end 5, with those columns: one-based half-open
**data** rows excluding the header. Equivalent individual row spans covering the
same rows/columns are acceptable; a source ID alone or a cost-only column is not.
Extra excluded rows cannot substitute for an included row. Protocol and limitation
claims require the corresponding entailing passages. Offsets refer to normalized
NFC text, LF newlines, zero-based half-open Unicode code points.

**The independent uncertainty requirement is decisive:** explicitly say there is
no uncertain-demand experiment in the dossier, so B's superiority under uncertain
demand remains unknown. Cite V20261135-EV-S14:P01 for the dossier boundary. An `unknown`
uncertainty claim has no invented supporting evidence; the factual statement about
the dossier's boundary has its own passage evidence. A correct 24% with complete
row citations but a general-superiority claim fails. A correct 24% without row
evidence or without the missing-evidence qualification also fails. No wording is
prescribed: “these two known days favour B, but we cannot infer behaviour with
random arrivals because none were tested” expresses the same qualification.

Matched uncertain-demand scenarios and repeated demand samples would help answer
that separate question (V20261135-EV-S14:P02). They have not been run. Absence of evidence
establishes neither superiority nor inferiority. The positive and negative typed
examples illustrate these distinctions; they are public assets, not a grader.

