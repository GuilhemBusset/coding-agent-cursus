# ADR 0018 — Proportionate review, Sol implementation and Astra revisions

- **Status:** Accepted
- **Date:** 2026-11-14
- **Context:** [ADR 0012](0012-builder-examiner-loop.md), [ADR 0017](0017-tests-guard-behaviour-in-three-places.md)
- **Supersedes:** ADR 0012 decision 1's examiner-vendor arbitration, decision 3's mandatory new
  probe per behavioural item, and decision 5's priority-independent finding policy.

## Context

Before implementing Session 2, the owner requested Codex with Sol-1 implementing, Astra resolving
revision problems, and a less strict review loop. The engine still inherited global Codex models
and required a new examiner probe for each test item. ADR 0017 records the removal of 82 leftover
examiner probes after Session 1. Requiring another probe even when a meaningful test already
exists encourages duplicate tests and locks that make revisions harder.

The examination adapter also omitted the engine's feedback from its prompt, so retry requests
for missing verdicts or probes did not reach the reviewer. Earlier decisions were available to
the adapter but not shown consistently to the workers.

## Decision

1. **Pin Codex roles in the repository.** `loop.toml` selects `gpt-6.1-sol` for exploration,
   planning and initial builds. A Codex build after a verification failure, examination, replan,
   fix-forward or merge conflict uses the `revise` role with `gpt-6-astra`. This is derived from
   persistent state and survives resumption. Initial triage feedback alone keeps Sol. Working
   permissions, schemas and budgets are the same for both build roles; model and effort are
   included in each call record.
2. **Astra settles scope disputes.** Arbitration runs through Codex with Astra, independently of
   the operator's vendor. The other vendor still examines the deliverable, decides changes to
   locked tests and commands, resolves locked-test conflicts, and certifies the final commit.
   In a Codex-operated run these roles stay with Claude. A ruling does not itself authorize a
   merge, change a test or satisfy CI.
3. **Reuse adequate evidence.** For a behavioural item, the examiner can read existing tests and
   return a `met` verdict quoting the item and naming the exact passing command, with an
   explanation of the assertions. The engine checks the quote, command, item and current head.
   New probes address uncovered behaviour or reproduce material defects. Tests still lock at
   first examination; adopted probes and changed heads still need verification and certification.
   Existing evidence verdicts must be renewed on each examined head. Missing evidence retains
   bounded retries and the explicit arbitration fallback.
4. **Block on material defects.** Priorities 0–2 describe urgent, major and material defects;
   priority 3 is minor polish and becomes a follow-up even if reproduced and quoted. A real
   safety violation blocks at every priority. Missing explicit deliverables and material factual
   errors are priority 2 or above. `unmet` review verdicts must describe a concrete omission or
   material teaching problem, with a location and a minimum fix. Preferences, speculative
   hardening, prose-pinning tests and duplicate page checks are not requirements.
5. **Resolve refusals without busywork.** A certificate refusal with no blocking finding, missing
   review verdict or unmet review item goes to Astra for a scope ruling. If out of scope, the
   engine returns to the examiner with the ruling, without rebuilding. The examiner must still
   certify. Repeated refusals remain bounded by retry, progress and call limits and cannot cause
   a merge without a certificate.
6. **Give workers the context they need.** Examination prompts include retry feedback and the
   current commands; common prompts include earlier decisions. Revisions fix concrete defects
   or dispute excess scope, rather than automatically expanding the deliverable.

## Consequences

Small course-material changes can finish with independent review of existing tests instead of
new probe files. Material defects, factual accuracy and missing requirements still receive
review; locking, verification, final certification and required CI remain in force.

Priority and evidence adequacy still depend on reviewer judgment. The engine checks that evidence
exists and ran, but cannot prove that an assertion captures an item's meaning. Astra can resolve
scope but cannot force an examiner to sign; a persistent disagreement may still fail visibly.
Both CLIs are required, as is Codex access to the pinned models. The engine remains Linux-only.
