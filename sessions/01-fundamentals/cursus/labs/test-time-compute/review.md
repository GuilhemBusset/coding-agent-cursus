# Test-time compute lab: review evidence

Agent review by the implementer, 2026-10-11. Reviewed file: `../test-time-compute.html`,
90,311 bytes, sha256 `1901e80a848d6f4f80bf93e096357112a5d2672f6d53aaa600441bf273e2b9ac`.
Any edit to the page invalidates this review; re-review and update the hash.

## Checks run

- `node tools/html-pages/check-page.mjs sessions/01-fundamentals/cursus/labs/test-time-compute.html`:
  PASS, 70 of 70 checks (offline `file://`, shared-asset hashes, axe, desktop 1440×900, laptop
  1280×720 and mobile 390×844 with no horizontal overflow, no-JS, reduced motion, print).
- `node tools/html-pages/tests/run-suite.mjs tools/html-pages/tests/test-time-compute.test.mjs`:
  the locked suite, 12 tests, all passing. It covers D1–D5, A1 (pass@N against exact identities,
  quadrature and a seeded 200k-draw Monte Carlo) and A2 (390 px stress states).
- The suite is registered in `setup/package.json` `scripts.test` and in the `suites` list of
  `tools/html-pages/tests/component-helpers.mjs`.

## Model choices

- Everything is closed form. There is no randomness in the page, so two loads and every Reset give
  identical numbers.
- `passAtN` sums log1p terms with compensated summation. The beta-binomial and binomial pmfs use
  ratio recurrences in log space, normalised from their maximum, so nothing underflows at N = 1024.
- Majority vote at N = 0 returns 0 (there is no answer to vote on). The chart starts at N = 1, so
  this edge never shows.
- The recommended mixtures were kept. Numerically, RL leads at k = 1 (48.4% vs 17.4%), there is
  exactly one sign change on 1..1024, the first k with base ≥ RL is 12, and base leads at k = 1024
  (96.4% vs 73.0%).
- The inverse-scaling curve peaks at x = 11 (2,048 tokens, 73.8%) and ends at 40.0% at x = 15.
- The best-of-N panel also prints the N → ∞ limits (majority → P(p > ½), verifier →
  E[p / (p + f(1 − p))]). They come from a midpoint rule after substituting p = x^(1/a) and
  1 − p = y^(1/b), which removes the endpoint singularities for a, b < 1. At the defaults they are
  10.2% and 54.7%.
- No-JS readers get a static SVG snapshot of each chart at the default settings, labelled as such
  in a `noscript` callout. The snapshot comes from the page's own renderer at phone width (a
  300-unit viewBox with 12-unit text), so it stays readable on a phone. A first version used a
  768-unit desktop snapshot, which shrank to about 6 px text at 390 px. On wider screens the
  snapshot is capped at 24rem; the cap applies only until the renderer marks the figure
  `data-ttc-drawn`.

## Screenshot review

Sources: the check-page screenshots plus per-panel screenshots from a disposable Playwright
script (deleted after use), at the default state and at a stress state (f = 1, N = 1024, inverse
task on at 32,768 tokens, k = 1024).

- **Desktop 1440 and laptop 1280**: the controls and readout sit in the left column, with the
  chart on the right. Text is 14 px. The series labels sit at the line ends with no collisions. The
  cost axis (top) and the token axis (bottom) of the effort chart both show all nine ticks. The
  crossing line and its "k = 12" label sit where the curves cross.
- **Mobile 390**: everything stacks into one column. Charts are drawn at the figure's real width
  (326 px), with 12 px text. Axis ticks thin to 1, 4, 16, 64, 256, 1024 (128, 2k, 32k for tokens;
  three cost ticks). The series labels dodge apart in the stress states: verifier and majority at
  f = 1, and inverse and hard at 32k. There is no horizontal overflow. I inspected the 390 px
  screenshots visually for all three panels in both states.
- **No-JS**: the static chart snapshots, formulas, assumptions, predict answers, citations and the
  "charts are computed in your browser" callout all show. The controls and predict buttons are
  disabled. With JavaScript off, a Playwright probe measured the chart text at:
  - 390×844: 326 px wide, scale 1.09, about 13 px text;
  - 360 px: scale 0.99, just under 12 px text;
  - 1280 px: 384 px wide, about 15 px text.

  At 390 and 1280 px, no text overlaps another text box or leaves its SVG. I looked at the
  per-chart screenshots at 390 and 1280 px and at print with JS on and off, and every label is
  readable.
- **Print**: the charts recolour through the theme variables (light paper, dark ink), the controls
  are hidden, and the formulas, readouts, answers and captions print.
- **Reduced motion**: no transitions or animations. The controls still work.

## Prose and citation review

I checked each citation against its arXiv abstract page on 2026-10-11.

- **Brown et al., arXiv 2407.21787, "Large Language Monkeys"**: accurate. The abstract says coverage
  scales with the number of samples over four orders of magnitude, and that majority voting and
  reward models plateau beyond several hundred samples. The best-of-N caption makes exactly this
  claim.
- **Snell et al., arXiv 2408.03314**: accurate. The abstract says the effectiveness of test-time
  compute "critically varies depending on the difficulty of the prompt", and that it beats a 14×
  larger model where the smaller model has "somewhat non-trivial success rates". The page says
  benefit depends on difficulty and pays off most where the model already has a non-trivial
  success rate. The page labels the per-difficulty sigmoids as a stylisation, not the paper's
  curves.
- **Gema et al., arXiv 2507.14417, "Inverse Scaling in Test-Time Compute"**: accurate. Its tasks
  include counting with distractors and regression with spurious features, and its failure modes
  include distraction by irrelevant information and drift to spurious correlations. The caption and
  predict answer say the same.
- **Yue et al., arXiv 2504.13837**: accurate. RLVR models beat their base models at small k, and
  the base models score higher pass@k at large k. The authors read this as the abilities being
  bounded by the base model. The page attributes that reading to them and labels it contested.
- **Liu et al., arXiv 2505.24864, "ProRL"**: accurate. It is cited as the counterpoint: prolonged
  RL that outperforms base models on pass@k, including on tasks where the base model fails
  however many attempts it gets.
- Every chart, caption and callout calls its numbers an illustrative simulation. The $10 per
  million tokens figure is labelled "illustrative price, not a vendor quote". No vendor, model or
  price claim needs an as-of date.
