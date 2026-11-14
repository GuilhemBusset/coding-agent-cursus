# B — Compare with a correction

[case.json](case.json) supplies the question and local P01 summary. All twelve
fictional sources are local in [corpus.json](corpus.json), so A need not have been
completed. The [key](reference.json), [typed examples](examples.json) and this worked
answer are public before students build.

**Question:** With finite shared slow/fast chargers and a solve limit of at most
60 seconds, which method is supported? Apply both constraints, incorporate the
dated correction, distinguish repeated reports from independent experiments, and
qualify the recommendation.

## Worked reference

Recommend **Queue Repair (`queue-repair`) conditionally for the tested setting**
(EV-S12:P02). It explicitly enforces finite shared charger occupancy (EV-S03:P01),
and its checked feasible solves take **42 seconds** on the reference day
(EV-E-Q1, EV-S07:P01) and **55 seconds** on an independent second deterministic day
(EV-E-Q2, EV-S10:P01). Both satisfy the at-most-60-second requirement. EV-S01:P03
defines the common timing boundary: construction through the first complete checked
feasible plan, on illustrative EVBench R1, without requiring proof of optimality.

| Method | Finite shared chargers? | Applicable solve time | Meets both? |
| --- | --- | --- | --- |
| Slot Ledger | Yes, EV-S02:P01 | Corrected 84 s, EV-S06:P01 | No: too slow |
| Queue Repair | Yes, EV-S03:P01 | 42 s and 55 s, EV-S07:P01 / EV-S10:P01 | Yes, on these tested days |
| Slot Ledger Private | No, EV-S04:P01 | 8 s, EV-S11:P01 | No: dedicated chargers |

**The correction changes eligibility.** EV-S05:P01 originally claimed Slot Ledger
was eligible with a 48-second solve. The later correction, dated 12 October,
EV-S06:P01, explains that the timed formulation omitted shared occupancy constraints.
The full formulation takes 84 seconds, so its earlier eligibility assertion is
superseded. Slot Ledger still *models* shared capacity; it fails the time constraint.
Using the old 48-second result with the shared-capacity description improperly
combines evidence from different formulations. Choosing the 8-second private
edition instead applies time but ignores sharing.

**Four Queue Repair reports contain two independent experiments.** EV-S07 is the
primary report of EV-E-Q1. EV-S08's digest and EV-S09's slides explicitly repeat it
(EV-S08:P01, EV-S09:P01). EV-S10 reports EV-E-Q2, a separate day/run. Thus the evidence
contains **two**, not four, independent Queue Repair experiments (EV-S10:P02).
They share family EV-F-Q because they study the same method. A family is neither
a document count nor a unique experimental run. Similarly, EV-S05 and EV-S06 are
initial/corrected reports of EV-E-L1, not two replications (EV-S06:P02).

The recommendation retains A's assumptions: known deterministic inputs, 30-minute
whole-wait charging, lossless constant power and truck/charger power bounds
(EV-S01:P02). Queue Repair is a checked feasible-plan heuristic on fixed candidate
routes with repair or cancellation, not a global optimum claim (EV-S03:P02).
The dossier contains no uncertain-demand experiment or cost-superiority evidence
(EV-S12:P01). It supports eligibility here, not universal runtime, cheapest cost,
or superiority under uncertain demand.

## Rubric and acceptable alternatives

The key has sixteen required facts. Fifteen are decisive: the conditional choice,
both requirements, each method's capacity eligibility, corrected Slot Ledger time
and exclusion, both Queue Repair times, repeat identity and independent count,
the common assumptions, and the absence of a global optimum guarantee. The private
edition's 8-second number is required background but is not decisive: its exclusion
follows from its capacity model. Report the required uncertain-demand limitation.
Attach entailing passages to factual claims; the old bulletin supports only a
historical description, not current eligibility.

Reasonable alternatives include “Queue Repair is the only supported eligible
candidate among these three on the tested days” or “use Queue Repair provisionally;
these two runs do not guarantee a one-minute solve on a new fleet.” Saying that no
method is *guaranteed universally* under 60 seconds is acceptable qualification if
the answer still identifies the supported choice in the stated tested setting.
Rejecting all methods without that distinction misses the question. Synonyms such
as “one minute”, “finite shared plugs” and “two distinct runs” are acceptable;
wording and ordering are not graded. There is no need to recommend an optimal
method because neither the question nor the timing definition requires optimality.

Another valid phrasing: “Use the route-repair method on the specified deterministic
half-hour model: its shared-capacity runs finish in 42 and 55 seconds. The ledger
method handles sharing but the corrected full solve is 84 seconds; its 48-second
claim omitted that constraint. The fast dedicated version cannot model the pool.
The digest and slides repeat the first run, leaving two experiments. The choice is
conditional, with no global-optimum or uncertain-demand superiority claim.” Cite
the passages above and retain the charging assumptions in a complete answer.

The public negatives in `examples.json` deliberately assert obsolete Slot Ledger
eligibility using EV-S05, or count all four Queue Repair reports as experiments.
Both are well-formed claims-v1 artifacts. Their failures are changed facts and
inadequate evidence, not forbidden wording. Public positives use different prose
and set ordering. Peer review checks actual entailment as well as typed facts.

## Public seeded variant

The [public manifest](../../fixed/config/public/manifest.json) announces
`public-seed-20261125` for class and all three independent submission trials,
identically for baseline and candidate. The [bundle](variants/public-seed-20261125/)
changes names, timings and source order, retaining the 60-second limit, correction
and duplicate-experiment lesson. Use its own public answer and reference. See the
[generation instructions](../../fixed/corpus/README.md). Deterministic inputs do
not promise deterministic model outputs.
