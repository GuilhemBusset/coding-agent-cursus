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
