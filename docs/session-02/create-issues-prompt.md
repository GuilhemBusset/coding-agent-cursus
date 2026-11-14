# Handoff prompt — create the session-2 implementation backlog

Paste the following into a new agent session in `GuilhemBusset/coding-agent-cursus`.

---

Create and publish the GitHub issues needed to implement the locked plan in
`docs/session-02/README.md`. This task is backlog creation: produce one tracking epic
and a complete, ordered set of implementable sub-issues. Do not implement the course,
launch the implement loop, or merge implementation PRs in this session.

Read `AGENTS.md`, the locked plan and its references, session 1's actual materials,
`setup/README.md`, `tools/test-impact/impact.toml`, and
`tools/implementation-loop/README.md`. Inspect existing issues and labels before
publishing; reuse relevant work and avoid duplicates. The locked plan supersedes the
older session-2 sections in `docs/cursus-narrative.md` and
`docs/cursus-key-technical-notions.md`. Preserve its teaching choices; resolve routine
implementation details and document your decisions in the epic.

Keep these agreed requirements in every relevant issue:

- Two hours, with harness construction first and prompt experiments afterwards.
  Students extend one runnable Pi program through model call, reading, search,
  evidence memory, numerical checking, recovery and stopping. Each stage states what
  the instructor says, what students edit/run, what they observe and how they rejoin
  from a completed checkpoint. All checkpoints and solutions are public from the start.
- Use Pi's `pi-ai` and `pi-agent-core` with a small TypeScript scaffold; keep corpus
  utilities and grading in Python. Provide fixed deterministic research tools; students
  progressively register and orchestrate them, then edit context, memory and control
  logic. This is a single-agent lesson inspired by Harness²'s improvement cycle.
- Start with a small OpenAI API model supporting tool calls. Select a currently
  supported model, verify Pi compatibility and pin its ID/snapshot during implementation.
  Document credential setup, supported generation settings, token accounting, cost and
  spending limits. Credentials stay out of source and traces. Keep endpoint/provider
  selection configurable for a later inference migration. Do not require, deploy or
  modify `research-harness-inference`; its readiness must not block this epic.
- Build the three self-contained EV-fleet cases: find method assumptions, reconcile
  conflicting evidence for a constrained recommendation, and audit a numerical claim
  while acknowledging missing evidence. Include the necessary P01 context locally,
  original clearly fictional sources, CSV data, references, rubrics, public variants,
  seeds and fault scenarios. No hidden answers, private holdouts or surprise tests.
- Store each answer key in `exercises/cases/<case>/reference.json`. Define required
  facts, decisive requirements, accepted evidence, numeric tolerances and uncertainty.
  Define schemas for `claims.json`, reports, traces and scorecards before their consumers.
  Deterministic checks grade facts and citation spans; peer review checks prose support.
- Keep fixed tools/evaluation support in `exercises/fixed/`, student work in
  `exercises/harness/` and `exercises/prompts/`, and outputs in `exercises/runs/`.
  Students can inspect everything. Document exactly which inputs/tools the research
  agent receives; use fresh run workspaces and a pinned public evaluator/fixture copy
  for rating. Do not describe this classroom arrangement as an adversarial sandbox.
- One evaluation command compares saved baseline and candidate versions on identical
  public cases and configuration. Measure requests/usage at the supplied adapter,
  including retries and failed runs. Report requirement failures, coverage, citations,
  pass rate, calls, stopping reasons and tokens per successful attempt. Zero successes
  fails. Quality gates precede efficiency comparisons; preserve earlier passing cases.
- Pilot the proposed 12-model-call, 20-tool-call and 30,000-token caps on the selected
  model; publish calibrated values before teaching. Use one public variant per case
  live and three trials per case for submission. Offline checks and replay support CI
  and outages; label live-model evidence separately and never invent measurements.

Decompose the work into small, independently reviewable issues covering:

1. Session structure, pinned tooling, cross-platform setup and the initial OpenAI/Pi adapter.
2. Public case specifications, corpora, numeric references, schemas and deterministic tools.
3. Evaluation runner, independent measurement, baseline/candidate comparisons and scorecards.
4. The progressive runnable starter, checkpoints, completed examples and prompt experiments.
5. Teaching materials: session hub, instructor run-of-show, explanations/demos and student
   instructions, following the repository's HTML skill when those pages are implemented.
6. Standalone exercises, submission integration, offline failure fixtures, appropriate CI
   selection, and a live pilot/rehearsal that verifies the two-hour workload.

Use these as coverage areas, not a requirement to make exactly six issues. Split work
when it cannot land as one coherent PR. Establish contracts before dependent components;
do not make tests, observability or documentation an afterthought. Reserve custom-service
integration for later; the current epic must be completable with OpenAI.

Each implementation issue must have a precise title, context linked to the locked plan,
suggested feature branch, affected paths, `## Deliverables` and
`## Acceptance criteria` with concrete checkboxes, validation commands/evidence,
explicit exclusions and appropriate existing labels, including `size:S`, `size:M` or
`size:L`. Every criterion must have an observable outcome; use tests for behaviour,
review for teaching clarity, and documented owner obligations for unavailable API
credentials, platform access or classroom rehearsal. Do not turn unavailable live
evidence into a fabricated pass or make CI require paid model calls.

Respect the repository boundaries: course material in `sessions/02-research-agents/`,
student work in its `exercises/`, lesson tests in `tests/lessons/`, lab tests in
`tests/labs/`, and repository-wide setup/manifests/diagnostics under `setup/`.
Student setup, exercises and turn-in must support Linux, macOS and Windows; instructor
HTML tooling only needs Linux. Add affected paths to the impact map when needed and
use `scripts/check-changed.sh` before shipping implementation. Do not write tests that
pin prose, slide counts or presentation details.

Publish the epic and sub-issues using native GitHub parent/sub-issue and blocked-by
relationships: the implement loop reads those links, not prose dependency lists.
Read back the resulting graph to verify attachment, ordering and absence of cycles.
Run the read-only `scripts/implement.sh plan <epic-number>` to check that the loop
discovers the intended work and dependencies; fix actionable graph warnings. Do not
start implementation. Finish with the epic URL, an issue/dependency table, a mapping
from the locked plan to the issues, and any remaining pilot or owner obligations.
