# Session 2 teaching fact check

Reviewed **15 November 2026**. Primary sources below were opened on that date.
Repository interfaces were checked against the public completed checkpoints and
examples present in this checkout. The locked course plan is
`docs/session-02/README.md` (14 November 2026); it supersedes the older system tour.

## Primary sources and the claims they support

| Primary source / date | Supported teaching claim | Classroom adaptation / limit |
| --- | --- | --- |
| [Pi AI README](https://github.com/earendil-works/pi/blob/main/packages/ai/README.md), rolling docs, accessed 2026-11-15; local package 1.5.2 | Model/provider selection and tool-call interfaces | Course adapter starts with configurable OpenAI/endpoint settings; local pins do not prove live compatibility. |
| [Pi Agent README](https://github.com/earendil-works/pi/blob/main/packages/agent/README.md), rolling docs, accessed 2026-11-15; local package 1.5.2 | Stateful tools and continuation; transformContext changes retained model context | Our memory hooks and fixed accounting/admission are course code, not guarantees awarded by Pi. |
| [Harness²](https://github.com/google-research/harness2), Xu et al., 2026; accessed 2026-11-15 | Prompts, tools, memory and orchestration form a harness; Propose–Probe–Compose contrasts executions | Published task-level probing uses no ground-truth feedback. Pairs here propose one edit and inspect public grades; no recursive improver or dependency on research-harness-inference. |
| [Harness² experiment guide](https://github.com/google-research/harness2/blob/main/docs/EXPERIMENTS.md), rolling docs, accessed 2026-11-15 | Fix comparison controls and separate incompatible outputs; task-order seed does not control model sampling | Our A–C schedule, fresh attempts and documented model-input boundary are local choices. Public references remain inspectable; no adversarial sandbox claim. |
| [Gao et al., ALCE](https://aclanthology.org/2023.emnlp-main.398/), EMNLP, December 2023; accessed 2026-11-15 | Fluency, correctness and citation quality are distinct dimensions | Typed assertions, accepted spans/rows, ≥80% fact gate and peer prose audit are our implementation, not ALCE’s exact metrics. Citation existence is not entailment. |
| [Anthropic, Demystifying evals for AI agents](https://www.anthropic.com/research/demystifying-evals-for-ai-agents), 2026-01-09; accessed 2026-11-15 | Separate tasks, trials, graders, traces and outcomes; repeat trials in clean environments | The one-trial class / three-trial submission schedule and tokens-per-success rule come from our locked plan. |
| [Anthropic, Building effective agents](https://www.anthropic.com/research/building-effective-agents), 2024-12-19; accessed 2026-11-15 | Simple composable patterns; model-directed tools differ from predefined workflows | This is background for one agent, not a multi-agent tour or evidence that the class fits two hours. The source flags subsequent tooling changes. |

## Teaching claims checked against runnable support

- **00–02:** `fixed/checkpoints/*/harness/main.ts` registers no tools, then read,
  then read/search. Pi continues after tool results. Scripts choose the offline
  model actions; `requests.jsonl` is the actual payload, not live autonomy evidence.
- **03 / B:** `memory.ts` ingests successful passage reads, records dates and
  correction relationships, and groups passage IDs by experiment ID. Search is
  discovery, not retained support. In the bundled last request EV-S06 supersedes
  EV-S05: 84 seconds replaces 48. EV-S07/08/09 share EV-E-Q1, 42 seconds; EV-S10
  supplies independent Q2, 55 seconds. Both shared capacity and ≤60 seconds matter.
  Slot Ledger fails the corrected time limit; Private lacks shared capacity.
- **04 / C:** check_table actually executes on EV-T01; its two feasible complete
  pairs use rows 1–4, totals 300 and 240, denominator 300, reduction 20%. Rows 5–8
  are excluded, including the feasible member of the infeasible pair. Figures are
  fictional cost units, not currency. EV-S14 says uncertain-demand evidence is
  missing. Retained calculation and next request contain actual row evidence.
- **04 / recovery:** one failed read and one successful identical retry have
  separate IDs; retry_of links them. Further research follows. Repetition and
  permanent absence produce explicit partial stops. Admission counts failed work;
  caps 12/20/30,000 are provisional, not calibrated recommendations.
- **Grading:** `fixed/grading/engine.py` independently grades saved artifacts;
  public references specify typed facts and accepted spans. IDs alone are not
  support. Structural completion does not award factual quality. Machine gates
  and pending peer prose review remain separate.
- **Experiments:** existing `fixed/examples/{harness,prompt,paraphrases}.json`
  compare saved versions with fixed controls. Harness candidate loses all cases
  despite 1440 → 720 scripted tokens; baseline 3 successes, candidate 0. Prompt
  pairs tie at 3 successes / 1440 tokens per version. Each returns exit 1/revert.
  Equality here cannot test prompt efficacy. Compare before/after traces, not just
  scores; full completed records are public beside the examples.
- **Input boundary:** launcher supplies question/context, active prompts, output
  contracts and registered tools; context hooks retain evidence. References and
  graders are public but not automatically passed to the research model. Local
  code execution is not an adversarial OS sandbox. Credentials stay in environment.

## Evidence labels and review record

The dossier sources (EV-S*, EV-T*) are **original fictional teaching material**;
their papers, experiments, seconds and costs are not findings of real EV research.
P01 supplies domain context only. Published references above support agent/eval
concepts, not dossier answers, live efficacy or the planned classroom timings.

Four sealed bundles in `../fixtures/research-loop/` were generated by
`../demos/research_loop.py prepare` on 2026-11-15 using real checkpoint execution
with scripted provider output/usage: **synthetic**, never captured live. The seal
is an integrity envelope, not proof of origin. Replaying them produces **replay**
with **source_evidence_kind: synthetic**. Captured live requires actual authorized
provider calls. No live run, live prompt effect, cap calibration or rehearsal is
claimed by these pages; those are separate pilot/readiness deliverables.

Content review: followed deck order against checkpoints 00–04 → fixed-prompt
harness experiment → frozen-code original/paraphrase prompt pairs → independent
machine and peer evaluation. Every build capability links its exact public
say/edit/run/observe/rejoin instructions; demo README provides executable outage
paths. Timing labels preserve the locked allocation, not observed duration.

## Validation evidence · 15 November 2026

- `node tools/html-pages/check-page.mjs <file>` passed for all four authored HTML
  files. Reports and screenshots are under repository-root `artifacts/html-pages/`:
  `01-build-09c4a23bd9b4-2026-11-15T08-48-47-654Z-800mJZ`,
  `02-experiments-9f52a5ba8afd-2026-11-15T08-49-11-063Z-K5RhAu`,
  `research-loop-e90f74d30b54-2026-11-15T08-48-02-484Z-lnzaq2`, and
  `sources-1b60f2e0fd9d-2026-11-15T08-43-24-291Z-xg91qB`.
  These are generated authoring evidence, not dependencies for viewing the pages.
- Inspected every deck slide at 1440×900 and the complete mobile renderings;
  inspected both reading pages at desktop/mobile. The final decks fit 1280×720
  without internal scrolling. Wide code and the comparison table scroll locally
  on narrow screens. No-JavaScript reading exposes all slides and trace events;
  native disclosures remain operable. Reduced-motion mode, emulated print and
  offline file URLs were checked. Physical printer pagination was not measured.
- Exercised deck navigation with pointer/keyboard through the generic checker.
  Exercised each trace controller with pointer, keyboard endpoints and reset;
  opened raw-record disclosures. The reusable browser suite compares all rendered
  event counters, request excerpts, memory indexes and final citations against
  the bundled files. No presentation or prose assertions were added.
- From the session, pinned Node 24.15.0 plus locked dependencies:
  `uv run --locked pytest -q -s tests/lessons/test_teaching_demos.py` passed
  (2 tests): prepare in a temporary workspace, all four generated and public
  replay fallbacks, intermediate read/search commands, rejoin preservation and
  partial-stop scenarios. Outputs print before temporary cleanup. No API keys.
- Reused `tests/labs/test_experiment_workflow.py` (6 passing tests) for the exact
  completed harness, prompt and paraphrase comparisons and their expected exit 1,
  controls and rejoin commands. No duplicated prose or outcome tests were added.
- Browser command: `node tools/html-pages/tests/run-suite.mjs
  sessions/02-research-agents/tests/lessons/research-loop.test.mjs` (1 passing test).
  Install authoring dependencies with `node setup/html-pages.mjs`; student runtime
  prerequisites and the module entry point are in the demo README. Page viewing
  itself installs nothing.
- Session typing and repository import-order checks passed. The required changed
  check plan selects everything because the impact map changed. Its first run
  caught the demo helper's dynamic import/path adjustment; the helper now uses
  ordinary session-local imports via `python -m cursus.demos.research_loop`.
  The focused 10-test session-layout check passed after that correction.

The artifact labels and manual teaching review support this offline deliverable
only. No unavailable live/API, native-platform or audience rehearsal check is
represented as passed here.
