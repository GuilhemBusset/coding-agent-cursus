# Offline typed-fact and citation grader

From the Session 2 directory, after a research attempt has stopped:

```sh
uv run --locked python exercises/fixed/grade.py --run exercises/runs/my-attempt --case exercises/cases/c-audit --policy exercises/fixed/config/policy.v1.json
```

`--case` is a public case directory, including a `variants/<seed>` directory when
that variant was attempted. `--run` must contain `config.json`, `trace.jsonl`,
`claims.json`, `report.json` and `report.md`. The reusable entry point is
`exercises.fixed.grading.engine.grade_run(run, case_directory, policy_path)`;
all three arguments are `pathlib.Path` objects. No dependencies were added.

The command validates the configuration and complete, ordered trace ending in
`run_end`, then the policy's schema, hash and configured budgets, **before opening
reference.json**. Unfinished or corrupt attempts cannot be graded. A terminal
failed attempt can be graded: missing/malformed research outputs are recorded as
quality failures, with its measured accounting retained. It makes no model or API
calls. Research artifacts are preserved; repeat grading refreshes only these
three evaluator outputs:

- `scorecard.json`: v1 structured assertions, coverage, gates, accounting and
  `peer_review: pending`.
- `grading.json`: each typed claim's matched and supported fact IDs, resolved
  evidence excerpts/cells, output errors, autonomy and separate budget status.
- `peer-review.md`: links from report anchors to claim IDs and source excerpts,
  plus an explicit audit of the entire report for assertions absent from claims.

Exit `0` means machine quality pass, `1` means a failed quality gate, and `2`
means invalid invocation, policy/configuration, case/reference or trace evidence.
This issue's required nonzero quality-failure exit supersedes the older generic
CLI allowance in `../contracts.md`. Peer review is never inferred from a machine
pass. No live compatibility, platform execution or classroom readiness is claimed
by these synthetic fixtures.

This standalone evaluator accepts explicitly selected local public assets and the
illustrative configs used by its fixtures. Publication, verified rating-bundle
selection, immutable snapshots and launcher admission/cancellation are supplied
by the later runner. A valid terminal trace establishes artifact ordering; its
truthful recording and exclusion of references from model inputs belong to that
launcher. This is not a sandbox or a guarantee against deliberately fabricated
research evidence.

## Machine checks

Facts match actual subject, predicate, type, value and unit. Fact-ID hints and a
candidate's `support_status` cannot award credit. Sets ignore order; numeric
comparisons use only the reference's inclusive tolerance:
`abs(actual - expected) <= max(absolute, relative * abs(expected))`.
Decimals are compared from their JSON numeric representations, so the inclusive
20.01-percent boundary is not lost to binary subtraction. Units must agree.

Each required reference fact contributes exactly once to the denominator,
including missing facts. Repeating claims cannot inflate the numerator. Required
facts count typed correctness independently of citations. The scorecard gives
individual `required_fact.<fact-id>` and `decisive.<fact-id>` results; the latter
must all pass even at 80% coverage. Unknown extra facts do not gain reference
credit and fail support checks.

Sources resolve by corpus ID to local files with LF newlines and Unicode NFC.
Passage offsets are half-open code points, and CSV spans are half-open, one-based
data rows without the header. Actual source bounds, passage quotes and CSV column
names are checked. Correct numeric content with irrelevant citations still fails;
matching a source ID, citation URL or containing range establishes no support.

Passage entries in `accepted_evidence` are alternatives. A supplied passage must
resolve to the full accepted supporting text; a shorter span is accepted only
when trimming boundary whitespace leaves the same content. Arbitrary shorter
semantic paraphrases/subspans are conservatively rejected. For row evidence, all
accepted row/column cells must be covered, possibly across split spans. Citing
only the cost column or omitting a feasible pair cannot pass. Repeated identical
citations are harmless, but every additional citation must be relevant. These
rules are deliberately inspectable and conservative, not a general entailment
algorithm. Broader passage acceptance requires an explicit reviewed reference
change, never a model judge.

Experiment identities are compared to the reference's distinct experiments;
multiple reports of one experiment do not create new experiments. Corrected
facts require corrected evidence, not obsolete reports. An obsolete claim left
in the final output still fails even if another claim supersedes it. Required
uncertainty must explicitly withhold the relevant subject/predicate using a typed
uncertainty assertion (`unknown`, `not-established`, or the reference reason),
with unknown support and no invented citation. Its explanation in prose is peer
reviewed. Evaluator-owned `absence` facts can be met by the matching abstention
without contradicting assertions; absence is a statement about the supplied
public inventory, never evidence of zero effect.

A decision requires accepted support for its typed conclusion **and** supported
decisive premises and scope. There is no general decision inference engine. The
public references define the decisions and premises that can be certified.

The provisional machine quality gate is the conjunction of:

1. Every decisive requirement passes.
2. Required-fact coverage is at least 80% (or a stricter supplied policy).
3. Every factual claim has valid supporting evidence.
4. Every decision is supported, including its decisive premises.
5. Required uncertainty is present and outputs/anchors are valid.
6. The trace contains no research-run human intervention.

Assertions have stable `category.target` IDs; `target_ids` identify the exact
requirement or claim that failed. Empty categories have a vacuous case-targeted
assertion. Intervention is independently recorded from boundary events and the
terminal event. Every failed/retried attempt stays in metering. Unknown usage
stays null. `grading.json` separately reports `within`, `exceeded` or `unknown`
for each budget. Budget observations do not alter factual quality or pretend to
enforce launcher dispatch. The 12/20/30,000 caps remain provisional, pilot pending.

## Following a report assertion

Copy `fixtures/pass-B` to a run directory and grade it with `b-compare`. In
`peer-review.md`, open the report link for `claim-B-ledger-seconds`:

> For slot-ledger, corrected_solve_seconds is 84 seconds.

Its anchor maps through `report.json` to that claim in `claims.json`. The typed
assertion gives subject `slot-ledger`, predicate `corrected_solve_seconds`, value
84 and unit seconds. `grading.json` identifies `B-ledger-seconds` and resolves
EV-S06 `[422, 859)` to the actual correction passage. The checklist includes the
passage and a file link. This route needs no exact prose matching. In case C the
same route exposes actual CSV rows and named cells supporting totals/percentages.

The reviewer checks whether **the actual sentence** follows from those passages,
including scope, qualifications and corrected premises. A typed assertion can be
correct while its associated prose exaggerates it. Also read every part of the
report, including text outside anchors: a factual or decision sentence omitted
from `claims.json` must be flagged and added or removed before the peer verdict
can be `supported`. Anchor completeness proves links for declared claims; it
cannot detect all undeclared prose assertions. Record that peer verdict separately
from the pending machine scorecard. No semantic-entailment guarantee comes from
IDs or anchors.

## Public offline fixtures and validation

Each directory under `fixtures/` contains a complete synthetic run. The manifest
names passing A/B/C runs and the right-ID/wrong-value, right-source/wrong-span,
unsupported extra claim, obsolete correction, duplicate experiment count, numeric
boundary, missing uncertainty and malformed claims/report failures, with their
expected failed assertion IDs. Copy fixtures before grading to preserve them.

Run every standalone grade command in temporary directories, print its exit and
failed IDs, and clean up on success or failure:

```sh
uv run --locked python -m exercises.fixed.grading.check_fixtures
uv run --locked pytest tests/labs/test_grading.py
uv run --locked --group typecheck ty check
```

The tests also exercise base and seeded public examples, unordered sets,
paraphrased reports, 4/5 coverage, decisive omissions, tolerance edges, missing
outputs, wrong cells/spans, interventions, retries, unknown/excess usage, denied
network access and pre-reference trace validation. All inputs are under the
existing session labs impact-map registration (`exercises/**`, `tests/labs/**`).
