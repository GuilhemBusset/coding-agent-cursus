# A — Find the capacity models

Read the question and local P01 context in [case.json](case.json), then use the twelve
fictional sources indexed by [corpus.json](corpus.json). This folder contains all
necessary data. The public [key](reference.json) and [examples](examples.json) are
available from the start. Source IDs and `Pnn` passage labels below resolve through
the corpus to exact text spans.

**Question:** Which methods model limited shared charger capacity, under which
common and method-specific assumptions? Explain their mechanisms and exclude the
similar-title private edition. A applies no runtime filter.

## Worked reference

The complete method set is **Slot Ledger (`slot-ledger`) and Queue Repair
(`queue-repair`)**, as scoped in EV-S01:P01. Slot Ledger bounds the number of trucks
charging at each depot, for each slow/fast type and half-hour slot by its charger
count (EV-S02:P01). Queue Repair maintains an occupancy ledger with the same finite
depot/type/slot capacity, shifting charges to valid slots or cancelling and rebuilding
routes rather than returning an unresolved conflict as feasible (EV-S03:P01).

Both assume known, deterministic daily legs, travel times, energy, tariffs and
availability. Charging uses 30-minute slots wholly inside depot waits, with lossless
constant-power energy bounded by truck and charger ratings (EV-S01:P02). These
assumptions matter: a per-truck energy limit alone does not limit how many trucks
share a depot's chargers.

Slot Ledger uses binary assignment/cancellation choices (EV-S02:P01), enforces
maintenance and battery bounds, and returns home with at least initial charge
(EV-S02:P02). Queue Repair fixes candidate routes for each repair pass, then repairs
or cancels and rechecks feasibility, including maintenance and charge bounds; it
does not claim a global cost optimum (EV-S03:P02). Its restricted route search is an
additional assumption, not a new optimality proof.

**Slot Ledger Private (`private-ledger`) is excluded.** It gives each truck an
always-available dedicated charger and lacks an aggregate depot occupancy bound
(EV-S04:P01). The shared Slot Ledger's corrected runtime in B does not remove it
from A's modelling set: A has no time limit. The dossier does not establish
performance under uncertain demand (EV-S01:P02, EV-S12:P01).

## Rubric and acceptable alternatives

The key lists ten required facts. Each is decisive for this retrieval task: identify
the complete set, explain both capacity mechanisms, state known inputs and the
slot/charging assumptions, include Slot Ledger's assignment and battery/maintenance
assumptions, include Queue Repair's fixed-route/repair/feasibility limitation, and
exclude the private edition. Cite the supporting passage for each assertion and
state that uncertain-demand performance is unestablished. No prescribed sentence,
source ordering or mathematical notation is required.

For example, “finite plugs per depot and charging type per half-hour” and
“a slot occupancy upper bound for each depot/type” express the same capacity fact.
“Known requests and energy” can express deterministic inputs if the explanation
makes clear that future demand is not stochastic in this model. “Repair heuristic
on preselected routes” is acceptable for fixed candidate routes; do not require the
word “heuristic” if the limitation and lack of optimality are clear. Either source
names or their method IDs are fine in prose. Sets may appear in any order.

An alternative complete phrasing: “Under deterministic inputs and whole-wait,
lossless half-hour charging, both the binary Slot Ledger model and the fixed-route
Queue Repair procedure cap simultaneous charger occupancy. The former includes
maintenance, state-of-charge and final-home-charge constraints. The latter repairs
or cancels until feasible, without proving optimality. The dedicated edition lacks
the shared constraint. None of this tests uncertain demand.” Attach the same
passages; this is a paraphrase, not a second answer key.

`examples.json` supplies two positive typed answers and an answer naming the right
methods but omitting deterministic-input and route-repair assumptions. That negative
fails because facts are missing, regardless of how fluent its prose sounds. For
peer review, also check that every factual sentence is entailed by its cited text;
IDs alone are insufficient. The common course quality gates are specified in the
public fixed policy; this rubric explains the case-specific decisive requirements.

## Public seeded variant

The [public manifest](../../fixed/config/public/manifest.json) announces
`public-seed-20261115` for class and all three independent submission trials,
identically for baseline and candidate. The [bundle](variants/public-seed-20261115/)
contains renamed methods, changed timings and reordered sources with recalculated
citations. Use its own public answer and reference. See the
[generation instructions](../../fixed/corpus/README.md). Deterministic inputs do
not promise deterministic model outputs.
