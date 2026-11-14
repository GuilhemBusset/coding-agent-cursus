# Public variants, trials and fault specifications

[manifest.json](manifest.json) is the complete announced inventory, published before
students build. Paths are relative to `exercises/`. A uses seed 20261115, B 20261125,
C 20261135. Each has one class trial and three independent submission trials using
the same per-case variant. Baseline and candidate receive the identical schedule,
provider/model/endpoint, settings, budgets and public rating support. New run and
request identities and fresh workspaces separate trials. Repeated model trials
measure variability: deterministic task generation does not imply deterministic
model outputs. Policy/model/bundle configuration remains provisional as marked in
the existing configuration; no live pilot or real-model outcome is asserted here.

Each file in `faults/` contains a visible deterministic trigger, preconditions,
scripted responses, worked solution and expected accounting/stopping consequences.
Roles such as “first passage” select the first source with passages in the bundle's
source order, then its first registered passage;
normal corpus data supplies exact successful passage text. Missing-source and
malformed-argument fixtures use the literal IDs in their triggers regardless of
variant. Responses are specification payloads, not complete trace/tool envelopes;
a later consumer adds the contract's run/request/attempt/tool IDs and hashes.
Budget fixtures describe a synthetic prefix already at the named limit, not a
paid or live sequence of operations. No injector, replay runner or grader is
implemented in this issue.

The scenarios are transient read failure (one retry), permanent absence (none),
repeated retrieval (stop after the third identical result), malformed final JSON,
malformed tool arguments, timeout, HTTP 429 rate-limit, each of the model/tool/token
budget limits, and absent usage. All retries and failures remain in counts. An
admission denied before dispatch adds no outbound attempt. Missing usage is null,
never zero; the absent-usage solution stops conservatively because remaining token
budget cannot be established. Fixtures are separate synthetic exercises; the normal
three-trial submission schedule is not evidence that fault replay or live calls
have happened. These public solutions guide the later implementation consumers.
