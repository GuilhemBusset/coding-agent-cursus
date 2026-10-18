# Act II deck: rehearsal record

**Status: pending.** No timed rehearsal has been run yet. A2 ("rehearsed to fit 45 minutes")
stays open until a person delivers the deck end to end, including the test-time-compute and
world-model lab activities, the effort-dial demo and the transitions, and fills in the table
below. An agent cannot give a spoken, timed teaching run, so this is the owner's step (ADR 0011).

## Planned schedule

The schedule comes from `data-minutes` on each slide of `../02-thinking.html`. The
speaker-notes summaries carry the same numbers, and `tools/html-pages/tests/thinking.test.mjs`
checks that they add up to 45.

| # | Slide | Planned minutes | Cumulative |
| --- | --- | --- | --- |
| 1 | Title | 0.5 | 0.5 |
| 2 | One forward pass | 1 | 1.5 |
| 3 | The autoregressive loop | 2 | 3.5 |
| 4 | System 1 and System 2 | 2 | 5.5 |
| 5 | Chain of thought adds depth | 2 | 7.5 |
| 6 | Test-time search (test-time-compute lab, best-of-N) | 8 | 15.5 |
| 7 | RL with verifiable rewards | 2 | 17.5 |
| 8 | Sharpen or expand | 2 | 19.5 |
| 9 | Effort dials across vendors | 1 | 20.5 |
| 10 | Effort-dial demo | 6 | 26.5 |
| 11 | Overthinking and inverse scaling | 2 | 28.5 |
| 12 | Unmentioned hints | 2 | 30.5 |
| 13 | 36 + 59 | 2 | 32.5 |
| 14 | Cues through tool output | 2 | 34.5 |
| 15 | Three meanings of "world model" | 1 | 35.5 |
| 16 | Internal representations | 2 | 37.5 |
| 17 | Kepler without Newton (world-model lab) | 3 | 40.5 |
| 18 | Learned simulators | 1 | 41.5 |
| 19 | The agent's picture of your repo (world-model planner) | 3 | 44.5 |
| 20 | Wrap | 0.5 | 45 |
| | **Total** | **45** | |

Cuts to make if a run goes over: replay the effort demo's recorded results instead of running it
live (about 3 minutes saved), and show the best-of-N panel as an instructor demo rather than a
student activity (about 3 minutes).

## Observed rehearsal

After a timed run, fill in one row per section. Record the deck's sha256 at the time of the run
(`sha256sum sessions/01-fundamentals/cursus/02-thinking.html`).

- Date:
- Deck sha256:
- Presenter:
- Agent CLI used for the demo (Claude Code or Codex):

| Section (slides) | Planned minutes | Observed minutes | Notes |
| --- | --- | --- | --- |
| The loop and depth (1–5) | 7.5 | | |
| Search, RL, sharpen or expand (6–8) | 12 | | |
| Effort dials, demo, overthinking (9–11) | 9 | | |
| Is the chain of thought the reasoning? (12–14) | 6 | | |
| World models and wrap (15–20) | 10.5 | | |
| **Total** | **45** | | |

Cuts made during the run:

Result (total observed minutes ≤ 45?):
