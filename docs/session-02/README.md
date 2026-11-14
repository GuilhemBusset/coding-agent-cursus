# Session 2 — Build an autonomous research harness

Locked teaching plan · 120 minutes · agreed 14 November 2026. This is the canonical
session-2 design, replacing the earlier system tour in the course narrative.
Implementation is pending. Numerical budgets remain subject to the documented pilot.

**Destination.** Students leave with a Pi-based program that takes one research question,
finds and compares evidence, checks a numerical claim, writes a cited answer, and stops
within a budget without human steering. It produces `report.md`, structured claims and
a run trace: session 1’s “model + tools + loop” put to work.

Use Pi’s [`pi-ai`][pi-ai] and [`pi-agent-core`][pi-agent] libraries: supply a small
TypeScript connection scaffold; students add tools, evidence memory and termination
logic. Python handles corpus utilities and grading. Keep one research agent and one
fixed model; students can use their familiar coding agent to help build it.

**Initial inference: a small OpenAI API model with tool calling.** Select and pin a
supported model ID/snapshot during setup, after a tool-call smoke test; record it and
the supported generation settings in every run. Supply credentials through the local
environment and document API costs and spending limits. The future
`research-harness-inference` service is not a prerequisite. Keep provider, model and
endpoint configuration behind the supplied Pi adapter so it can be connected later;
rerun the same compatibility checks and recalibrate budgets when switching providers.

The teaching rhythm is **predict → run → inspect the failure → change one thing → rerun**,
in pairs with alternating drivers. Borrow **Propose–Probe–Compose** and retaining
evidence-backed lessons from [Harness²][harness2]. This classroom adaptation uses
student-proposed changes and public checks; Harness²’s task-level refinement instead
probes changes without ground-truth feedback.

**Everything is visible from the start:** cases, sources, expected answers, grading
rules, variant seeds, injected failures and completed checkpoint code. Students begin
with a runnable model-call scaffold and extend the same program throughout. Each
checkpoint names one capability to add, a small edit to make and a command to run;
its completed version is available whenever a pair needs it. Progress comes from
implementing and understanding each capability, with no locked materials or surprise
tests. If a simpler version passes, inspect why before adding more machinery.

**The two hours**

| Minutes | How the step is driven | What students gain |
| --- | --- | --- |
| 0–10 | “What can this model actually know?” Run the starter on A; compare its answer with the public reference and inspect the trace. | A working baseline and an observable evidence gap. |
| 10–25 | “Give it access to one source, then let it find the next.” Add `read(source_id)` first, then `search(query)`. Watch Pi request a tool, receive its result and choose another action. | Two runnable checkpoints: reading, then autonomous retrieval. |
| 25–45 | “Which source supports this claim?” Run B; add a claim–passage ledger and unresolved-question list, then rerun the same prompt. | A third checkpoint: retained evidence, conflicting sources and duplicate detection. |
| 45–65 | “Check the number, then decide when to stop.” Add `check_table` for C, output validation and budgets. Enable the documented read-failure fixture and add a bounded retry. | A fourth checkpoint: verified output, recovery and stopping on completion, no progress or exhausted budget. |
| 65–70 | Short break; pairs leave a failing trace on screen. | A shared debugging starting point. |
| 70–85 | Propose one harness change, predict its effect, probe the same case, then keep or revert. Share a trace-supported lesson. Keep the prompt fixed. | Controlled improvement; quality and resource use measured together. |
| 85–105 | Freeze code. Compare a vague prompt with one specifying question, scope, evidence, uncertainty and output. Swap paraphrases and rerun. | Prompting as a separate variable, after harness construction. |
| 105–120 | Run the announced public variants of A–C. Inspect scores and a citation; explain one change using before/after traces. | Autonomous execution and an explanation of which capabilities helped. |

**Three use cases, one accumulating research task.** Ship an original, explicitly
fictional EV-fleet research dossier: about twelve short method notes, dated corrections,
distractors and a tiny results CSV. Include the P01 problem summary locally, so prior
homework completion is unnecessary. Fixed evidence makes research decisions checkable.

| Case and example prompt | Deliberate difficulty and rationale | Required evidence for passing |
| --- | --- | --- |
| **A — Find.** “Which methods model limited charger capacity, and under what assumptions?” | Relevant details are scattered; similar titles distract. Teaches retrieval before synthesis. | Correct method set and assumptions, each linked to a supporting passage. |
| **B — Compare.** “For this fleet with shared chargers and a 60-second solve limit, which method is supported by the dossier?” | A correction changes an eligibility claim; two documents repeat one experiment. Extends A into source reconciliation and a conditional recommendation. | Apply both constraints, incorporate the correction, and avoid counting duplicate evidence as independent support. |
| **C — Audit and qualify.** “Does the CSV support ‘method B is 20% cheaper’, and does that establish superiority under uncertain demand?” | Feasible and infeasible runs are mixed; no uncertain-demand experiment exists. Extends B into computation and justified abstention. | Recompute the comparison on the specified feasible paired runs, cite rows, and distinguish the measured result from the unsupported generalisation. |

Ship task contracts, prompts, paraphrases and public seeded variants changing values,
names and source order. Announce the evaluation seeds before building starts.

**How we rate it.** The instructor supplies the evaluation runner separately from
the student harness. Each case's public `reference.json` stores required facts, accepted
supporting passages, numeric values/tolerances and expected uncertainty. These are
instructor-reviewed assertions, allowing multiple valid phrasings. Code grades
`claims.json` against them; peer review checks the report's prose support. Matching
IDs alone cannot establish entailment. Separate correctness from citation quality,
following [ALCE][alce]. Runtime research tools return source evidence and calculations;
the evaluator reads reference answers after the research run finishes.

Proposed pass gates: all decisive case requirements above, at least 80% of the contract’s
required facts, valid citations for every factual claim, no unsupported decision claim,
and no human intervention. Initial caps: 12 model calls, 20 tool calls and 30,000 total
input-plus-output tokens per run, including retries. Pilot and freeze these targets
before class. Code enforces caps and records the stopping reason.

Report each case’s pass rate and **total tokens across all attempts / successful
attempts**; zero successes is a failure. Compare efficiency after quality gates pass.
Log elapsed time and service errors, but do not rank students on shared-server waiting.
Run one announced variant per case live, then three trials per case for submission. Fix
model, sampling, corpus and budgets; save harness/prompt hashes. Use fresh runs and
repeated trials, following [evaluation guidance][evals].

For each change, the evaluation command runs the saved baseline and candidate on the
same public cases and records usage at the supplied model/tool boundary. It writes a
before/after scorecard with failed assertions, coverage, citation checks, tokens, calls
and stopping reasons. Students retain a change when it fixes a requirement without
regressing earlier cases, or reduces resource use while preserving quality. The fixed
runner owns measurement; the candidate cannot award itself a passing score.

**Self-contained, even while students edit the repo.** Plan
these paths under `sessions/02-research-agents/exercises/` (to be implemented):

| Path | Contents and ownership |
| --- | --- |
| `cases/<case>/` | Public question, sources/provenance, `reference.json` and rubric; supplied by the instructor. |
| `fixed/` | Supplied source-reading, search and table-calculation functions, model adapter and evaluator. Students register the tools progressively in Pi. |
| `harness/`, `prompts/` | Student changes: tool wiring, context, evidence memory, retries, stopping and instructions. |
| `runs/` | Each version's report, `claims.json`, trace, configuration and scorecard. |

Lab checks belong in the session's `tests/labs/`. For rating, load cases and fixed
support code from a pinned, public course revision so local edits cannot change the
answer key or grading rules.

Launch research runs in fresh temporary workspaces with documented inputs: the task,
corpus-ID tools, table checker and report output. Students can inspect the entire repo,
including references and graders; these are not automatically sent to the research
model. Show this boundary in the launcher. Public variants let pairs demonstrate
reuse; this exercise assesses working research behaviour and their explanation of it,
not performance on secret tests. Tool scoping is not an OS sandbox for student code.

**Preparation required.** Provide checkpoints so a stuck pair can rejoin. Put pinned
Node/Pi setup and diagnostics under `setup/`; verify Linux, macOS and Windows. Pilot
the small OpenAI model through Pi for authentication, streamed tool calls, usage,
timeouts, cost and classroom request limits. Supply deterministic offline checks and
outage replay traces; replay cannot certify live autonomy. Only inference requires
a service; cases and grading work from the repo. [Pi's compatible-endpoint support][pi-models]
is the migration path when the custom inference service is ready, with integration
verified at that time.

**Appendix — resources and design choices**

- [Pi model API][pi-ai], [agent core][pi-agent], [endpoint configuration][pi-models]: the small, inspectable building blocks and connection boundary.
- [Harness²][harness2] and its [experiment guide][harness2-experiments]: contrast executions, retain supported improvements, control comparisons; public benchmark answers can leak into runs.
- [Building effective agents][patterns] and [Anthropic’s research-system account][research]: simple composable loops, evidence gathering and iteration; delegation adds coordination and token costs, so it is an extension after the core lesson.
- [ALCE (Gao et al., 2023)][alce] and [Demystifying evals for AI agents][evals]: citation support, answer coverage, separate graders and repeated trials.
- [OpenAI model catalog][openai-models]: verify a supported small model and pin its identity during implementation; no live API compatibility or cost measurements have been made for this lesson yet.
- Repository context: [session 1](../../sessions/01-fundamentals/README.md), [P01](../../sessions/01-fundamentals/exercises/homework-p01/PROBLEM.md), [course narrative](../cursus-narrative.md), [session isolation](../adr/0001-self-contained-per-session-subfolders.md).
- Future infrastructure context: sibling `research-harness-inference/README.md`, `docs/design/system-design.md`, and backlog drafts `E2/54-cli-harness-setup.md`, `E2/79-gateway-student-metrics.md`; these informed the later adapter boundary and are not needed to implement or run this session.

[pi-ai]: https://github.com/earendil-works/pi/blob/main/packages/ai/README.md
[pi-agent]: https://github.com/earendil-works/pi/blob/main/packages/agent/README.md
[pi-models]: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md
[harness2]: https://github.com/google-research/harness2
[harness2-experiments]: https://github.com/google-research/harness2/blob/main/docs/EXPERIMENTS.md
[alce]: https://aclanthology.org/2023.emnlp-main.398/
[evals]: https://www.anthropic.com/research/demystifying-evals-for-ai-agents
[patterns]: https://www.anthropic.com/research/building-effective-agents
[research]: https://www.anthropic.com/research/multi-agent-research-system
[openai-models]: https://developers.openai.com/api/docs/models
