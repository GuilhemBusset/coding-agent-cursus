# Public EV research cases

Start with [A — Find](a-find/README.md), then [B — Compare](b-compare/README.md).
Each folder is standalone: `case.json` contains the question and necessary local P01
summary; `sources/` and `corpus.json` contain the entire evidence bundle. No prior
homework, Session 1 files, web retrieval, solver or API access is needed to solve them.
The same twelve sources are copied into both cases with the same logical identities.
Copies are packaging, never extra experimental evidence.

**Everything here is public before building starts.** Each case includes its
`reference.json`, worked answer and rubric in `README.md`, and positive/negative
typed examples in `examples.json`. Runtime tools should expose the corpus, not look
up the reference. Public visibility is for learning and review, not a hidden holdout.

All EV sources, methods, authors, timings and experiments are original, explicitly
fictional teaching material. P01 supplies only the genuine course problem concept:
40 legs, 10 electric trucks, half-hour charging, battery feasibility, finite shared
chargers and daily cost. Its provenance and sufficient rules are embedded in each
`case.json`; no invented result is attributed to P01 or a real paper.

## Reading the evidence

`corpus.json` maps each stable source ID to a local UTF-8 Markdown file, date,
provenance, reporting relationship, experiment IDs and family IDs. Each passage has
a stable `passage_id`, an exact `quote`, and `start`/`end` offsets. Read with universal
newlines (CRLF/CR become LF), then normalise Unicode to NFC. Offsets count Unicode
code points, zero-based and half-open, over the **whole source file**, including its
header. They are neither UTF-8 byte offsets nor JavaScript UTF-16 indices.

The v1 reference contract uses `{source_id, kind: "passage", start, end}`; join that
span to its manifest passage for a human-readable ID and quotation. Every accepted
span in A/B is a complete manifest passage. Each listed span is an acceptable
supporting alternative for that fact; separate facts express separate assumptions.
Support still requires the passage to entail the assertion: matching a fact ID or
an experiment ID alone proves nothing.

| Sources | Purpose | Experiment / family |
| --- | --- | --- |
| EV-S01–EV-S04 | Scope, shared methods, similar-title private distractor | none |
| EV-S05, EV-S06 | Initial Slot Ledger report and its dated correction | EV-E-L1 / EV-F-L |
| EV-S07, EV-S08, EV-S09 | Primary Queue Repair report, digest and slides of one run | EV-E-Q1 / EV-F-Q |
| EV-S10 | Independent second Queue Repair day | EV-E-Q2 / EV-F-Q |
| EV-S11 | Fast dedicated-charger distractor | EV-E-D1 / EV-F-D |
| EV-S12 | Limits and conditional decision | none |

The correction preserves the logical experiment identity; it replaces a defective
formulation's time with the full formulation's time. It is not a replication.
`historical_facts` in B's corpus records the retired B eligibility assertion so
`supersedes_fact_ids` can resolve it without treating it as a current accepted fact.
The two Queue Repair experiments share a method family but are independent runs;
three documents reporting EV-E-Q1 are one experiment. Count experiments, not files
or families. No uncertain-demand result or cost-superiority evidence is present.

## Contracts, examples and offline checks

Cases and keys use the existing closed v1 contracts in `exercises/fixed/schemas/`.
Questions stay in `case.json`; worked prose, paraphrases and rubrics stay beside the
key rather than extending that contract. Numeric tolerances are zero for the exact
reported illustrative integers; they do not describe real-world precision.

`examples.json` contains complete claims-v1 artifacts plus review annotations.
The positives include a different prose formulation and reversed set ordering.
The negatives are structurally valid claims with factual defects: omitted
assumptions, stale eligibility evidence, or duplicated experiment counting.
`failed_fact_ids` names their intended differences; it is not an answer-matching
algorithm. The asset tests check typed differences and span relationships, not
prose wording. They do not implement the later runtime evaluator.

From `sessions/02-research-agents/`, run:

```sh
uv run --locked pytest tests/labs/test_cases_ab.py
```

This validates the contracts, resolves every accepted span and exact quotation,
checks correction/experiment relationships, exercises malformed-asset mutations,
and checks the public fact examples. Source entailment and teaching quality also
need review; passing structural checks alone does not certify prose support.

## Reserved identities for later work

These namespaces are reservations, not delivered C data or generated variants:

- Keep `A`/`a-find`, `B`/`b-compare` and `base`; reserve `C`/`c-audit` for the numeric
  case. A new source or changed passage meaning gets a new identity; do not silently
  retask EV-S01–EV-S12 or their `EV-Snn:Pnn` passages.
- Reserve `EV-T01` for C's fictional results CSV, `EV-T01:R0001` etc. for logical
  data-row IDs, and `EV-PAIR-0001` etc. for feasible comparison pairs. The manifest
  must record path, origin, date, columns, experiment/family IDs and pair identity.
  Rows-v1 spans are one-based half-open data rows, excluding the header. Row IDs
  stay stable when packaging changes; row offsets must be regenerated on reorder.
- New experimental runs use unused `EV-E-*` IDs and declare a family `EV-F-*`.
  Reprints retain the run identity and name the primary report. Changed methods,
  input days or corrected formulations must describe their relationship explicitly;
  no claim of independent support follows merely from a new document ID.
- Reserve variant IDs `public-seed-<integer>` and corpus IDs
  `ev-dossier-v1.public-seed-<integer>`. Record the announced seed, base revision,
  transformation and base-to-variant source/passage/row mapping in the variant's
  provenance. Use a `V<integer>-` prefix for transformed source, experiment and
  family IDs. Recompute offsets, quotations and references when values or names
  change. Shuffling source order alone must not create independent experiments.

## Content review recorded for issue #181

Builder review: each folder supplies its own question, P01 rules and all evidence.
A's complete set is Slot Ledger and Queue Repair; the common assumptions and each
capacity mechanism are explicit, and fixed-route repair is distinguished from
optimisation. B's full Slot Ledger model still handles sharing, but its corrected
84-second solve exceeds the limit. Queue Repair's 42- and 55-second runs satisfy
both requirements in the tested setting; the 8-second private method fails sharing.
The digest/slides identify their primary experiment, giving two independent Queue
Repair experiments, not four. All sources label their findings fictional. Rubrics
accept synonymous explanations and conditional eligibility, and require uncertainty
where generalisation is unsupported. The public keys and examples are available
beside the questions. The examiner independently reviews these content conclusions.
