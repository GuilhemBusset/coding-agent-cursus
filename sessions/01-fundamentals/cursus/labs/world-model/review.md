# World-model lab: review evidence

Agent review by the implementer, 2026-10-11. Reviewed file: `../world-model.html`,
103,568 bytes, sha256 `98247895ee8be22891bb7f9cc28198158e8a5fb856a04eae62f78e8343582b51`.
Any edit to the page invalidates this review; re-review and update the hash.

## Checks run

- `node tools/html-pages/check-page.mjs sessions/01-fundamentals/cursus/labs/world-model.html`:
  PASS, 0 failed checks (offline `file://`, shared-asset hashes, axe serious/critical, desktop,
  laptop and 390 px with no horizontal overflow, no-JS, reduced motion, print).
- `node tools/html-pages/tests/run-suite.mjs tools/html-pages/tests/world-model.test.mjs`:
  15 tests, all passing, in about 2 minutes. The closed-loop records are large, about 20–25 MB of
  JSON per run, because each plan carries its full CEM diagnostics so the suite can re-derive it.
- `node tools/html-pages/tests/run-suite.mjs tools/html-pages/tests/components-tooling.test.mjs`:
  passes with `world-model` registered in both `setup/package.json` and `component-helpers.mjs`.

## Demonstration and robustness (illustrative world, seeds chosen by nobody but the PRNG)

The defaults are seed 20261011 and model error 0.50. On those defaults the open loop hits the
obstacle at step 11. Its real endpoint is 5.16 from the endpoint its own plan predicted, against a
goal radius of 0.5. The closed loop reaches the goal at step 25 after 25 plans. At error 0 both
loops reach the goal (open at step 25, closed at step 22). At error 1.00 the open loop misses
and the closed loop reaches on the default seed. On seed 92821 at error 1.00 both hit the
obstacle, which the page's "Try this" item 3 points at.

I checked the default against 40 seeds (20261011 plus 7, 1020, …, 38501) with a Node copy of
the page's core. At error 0, both loops reached the goal on 39 of 40 seeds. At error 0.50, 40 of
40 showed the demonstration: closed reaches, open fails, and open drifts more than the goal radius
from its prediction. The default is therefore not a cherry-picked seed. The obstacle geometry
(centre (5, 3.625), radius 1.375) uses binary-exact values because SVG lengths read back as
float32. Of the exact candidates I tried, it was the most robust.

One design point worth a reviewer's eye. The required cost only scores the position after H
steps, so a receding-horizon replanner can postpone arrival forever. In the prototype, the closed
loop never arrived. The planner therefore uses a time-varying CEM sampling spread: wide before
the committed arrival step 15 (or the next 4 steps once that has passed), 20× narrower after it.
Replans are warm-started from the shifted previous mean plus a "stop" action. The page explains
this under "Planner details". It changes only the sampling distribution, not the cost, the elite
update or the executed-action rule.

## Performance (one-shot measurement)

Environment: Linux under WSL2 on an Intel Core Ultra 9 285K (24 threads), Playwright 1.63.0
Chromium, 1280×720. Node 26.4.0 drove the measurement; CI uses Node 22.

- Unthrottled: the shared step-0 plan takes 2.5–6.2 ms. One Step (open step + closed replan)
  takes a median of 2.7 ms and at most 7.1 ms over 55 steps at errors 0.50 and 1.00.
- 4× CPU throttle (`Emulation.setCPUThrottlingRate` rate 4): the step-0 plan takes 10.4–19.7 ms.
  A Step takes a median of 11.1 ms and at most 25.7 ms. A full Run at error 1.00 took 3.9 s, with
  no long tasks; the median frame gap was 16.7 ms and the worst 16.8 ms.
- Safety margin: the worst throttled step (25.7 ms) is about 2× below the 50 ms long-task
  threshold and about 5× below the 125 ms Run interval (8 steps/s). Slider and seed input only
  reset the view and schedule one step-0 plan on the next frame. They never simulate a run, which
  the suite asserts. The one long computation is the period scan for the two orbit fits at page
  load: about 50 ms in Node, once, before any interaction.

## Screenshot review

Sources: the check-page screenshots above, plus a disposable Playwright script (deleted after
use). It stepped both loops to the end at errors 0.50, 1.00 and 0, set the added mass to 0.030 and
0.012, and captured the result at 1440×900 and 390×844.

- **Desktop (1440×900):** masthead, then panel 1 with the illustrative callout, both dynamics
  formulas, the provenance sentence (200 training transitions, seed), the CEM sentence with
  N = 60, K = 8, I = 12, H = 30 and the cost, then the controls. The two worlds sit side by side
  at the same scale, each with start, obstacle and goal labels, a solid actual path, a dashed
  amber predicted path, a legend and an Outcome / Distance / Plans readout. At the default end
  state the open world shows the dashed prediction curving below the obstacle into the goal while
  the solid path runs into the obstacle ("Hit obstacle", 5.11, 1 plan). The closed world shows a
  path around the obstacle into the goal ("Reached goal", 0.50, 25 plans).
- **Max error (1.00):** the open path veers up and left, past the start, and ends top-centre
  ("Missed goal", 3.03). The closed path loops over the top into the goal ("Reached goal", 0.48,
  23 plans). The outcome labels match the geometry.
- **Laptop (1280×720):** same layout, narrower. Nothing collides.
- **Mobile (390×844):** single column. The worlds stack with their legends and readouts below
  each, and the readout grid becomes one column. Controls stack. The coefficient table scrolls in
  its wrapper. No horizontal overflow.
- **Max mass (0.030):** the added-mass marker and label appear at (1.5, 1.25). The true orbits
  become precessing rosettes while the dashed fits stay on the old ellipses. The readout says
  "Worst held-out error: 53.4% of orbit size (inner 53.4%, outer 32.0%)" with a red border and
  the "no longer predicts" verdict. At 0.012 it reads 22.5% / 13.6%. At 0 it reads 0.3% (inner
  0.0%, outer 0.3%) with the "still predicts" verdict. An earlier draft put the orbit labels on
  top of the orbit lines; they now sit inside the inner orbit and above-left of the outer one.
- **No-JS:** a callout says the simulations need JavaScript and describes the static snapshot.
  Both worlds show obstacle, goal, start and the dashed step-0 plan for the default seed and
  error. The orbit plot shows both baseline orbits with their fits. The controls are visible but
  disabled, the readouts show step 0, and the formulas, closing card and sources read normally.
- **Print:** light palette, one column. Controls are hidden, the worlds print stacked, and both
  details (coefficients, planner details) are expanded.
- **Reduced motion:** Run is hidden, the status reads "Step mode (reduced motion)", and only Step
  and Reset change state. The page has no CSS animation; check-page found no running animations
  or transitions.

## Prose and source review

- **Closing card (`#agents`):** it maps the learned dynamics model to the agent's picture of the
  repo, the observation to test and tool output, and replanning every step to the agent loop
  (small change, run tests, read output, replan). It also maps open loop to writing the whole
  change unrun, and the frozen fit to a picture that breaks on an unseen change. Each mapping
  refers back to what the panels showed: the dashed line still ending in the goal, the run that
  hit the obstacle, panel 2. It states plainly that feedback is not a guarantee and that a badly
  wrong picture should be fixed rather than looped on. It names no CLI or vendor, so the advice
  applies to Claude Code or Codex alike (ADR 0002).
- **Labelling:** each panel opens with an "Illustrative simulation" callout. Panel 2 says it is a
  stylised analogy, not a reproduction of Vafa et al.'s transformer experiments. The footer
  repeats that there is no measured data. The page makes no "latest" claims.
- **Sources:** Vafa et al. (arXiv 2507.06952), V-JEPA 2 (arXiv 2506.09985), and LeCun 2022 on
  OpenReview, which is framed as a position paper. CEM with replanning (MPC) is framed as standard
  control practice. The source descriptions stay at the level of the papers' abstracts as I know
  them. Limitation: this run had no web access, so I did not re-fetch the abstracts. A reviewer
  should confirm the one-sentence summaries and the author names against the three URLs.
