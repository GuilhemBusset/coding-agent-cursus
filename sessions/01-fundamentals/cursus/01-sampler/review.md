# Act I deck: review evidence

Agent review by the implementer, 2026-10-16. Reviewed file: `../01-sampler.html`,
76,582 bytes, sha256 `e887145f716a7f7455c2c2966cbd098a9f3ce97e735892685fc1e37cd1909508`.
It quotes `../fixtures/base_vs_instruct.json` (sha256
`964560825d740725d21d21fcdd431c92485262b28cf6b2a32fd12155a7aed105`) and reads numbers from
`../fixtures/next_token.json` (sha256
`5d2b12308990c09e3467ecc40e93d7bd9792a72f956c2e53c3c5ef8f26f722c4`).
Any edit to the deck invalidates this review; re-review and update the hash and size.
The cross-vendor reviewer confirms each section below against the deck at this hash.

The deck has 18 slides, each with one collapsed `details.speaker-notes` whose summary gives its
minutes (also in `data-minutes`; the total is 45). Concept slides come before their widget:

| # | Slide id | Min | Content |
| --- | --- | --- | --- |
| 1 | `title` | 1 | Agenda |
| 2 | `factorization` | 3 | p(x_t \| x_<t), chain-rule factorization |
| 3 | `tokens` | 2 | Integer IDs, " strawberry" = 41236 |
| 4 | `tokenizer-lab` | 3 | `labs/tokenizer.html` |
| 5 | `strawberry` | 4 | Demo slot, `demos/model/strawberry.md`, pivot to code |
| 6 | `distribution` | 3 | Distribution, softmax(z/T), System 1 named |
| 7 | `next-token-lab` | 4 | `labs/next-token.html` |
| 8 | `tiny-lm-lab` | 3 | `labs/tiny-lm.html` |
| 9 | `reproducibility` | 3 | Why outputs differ, `demos/model/sampling.md` |
| 10 | `attention` | 2 | Soft database lookup |
| 11 | `attention-lab` | 3 | `labs/attention.html` |
| 12 | `pretraining` | 2 | Lossy compression, arXiv 2309.10668 |
| 13 | `post-training` | 3 | Base vs assistant, `factual` fixture item |
| 14 | `rlvr` | 2 | Verifiable rewards, arXiv 2411.15124 |
| 15 | `cutoff` | 1 | Knowledge cutoff, context can add newer facts |
| 16 | `hallucination` | 2 | No truth oracle, structural |
| 17 | `or-stake` | 2 | Illustrative minimize vs maximize |
| 18 | `system-1` | 2 | Fixed compute per token, hand-over to Act II |

This plan is not a rehearsal; see `rehearsal.md`.

## Screenshot review (all views)

Source: `node tools/html-pages/check-page.mjs sessions/01-fundamentals/cursus/01-sampler.html`
(PASS, 0 failed checks) and `node tools/html-pages/tests/run-suite.mjs
tools/html-pages/tests/sampler.test.mjs`, which writes notes-open and print screenshots to
`artifacts/html-pages/sampler/`. A disposable script (kept outside the repository) measured
`scrollHeight − clientHeight` for every slide at 1280×720 and 1440×900 (0 px for all 18), and took
element screenshots of four slides at 390×844.

- **Desktop (1440×900):** each slide sits in the paged frame with the masthead
  (“Session 1 · Act I · 45 minutes”, “The sampler”), the slide, the navigation row and the
  footer. Content is top-aligned and the speaker-notes summary sits at the bottom of the slide.
  The formulas are monospace at about 1.5–2.25 rem. On the OR-stake slide the two code lines are
  large, one per row, with a teal and a coral left rule. The sentence below names which one
  matches, so colour is not the only cue.
- **Laptop (1280×720):** all 18 slides fit without internal scrolling. Earlier runs overflowed on
  `tokens`, `attention` and `post-training` by 7–9 px. Compact process rows, shorter copy and
  tighter quote padding fixed it. Dense slides (`post-training`, `distribution`, `rlvr`) leave
  about 10 px. The post-training comparison has the question on one row, then base and
  assistant side by side; the full 40-character revisions wrap inside the `.cite` line. With
  notes open (`notes-1280-*.png`), the notes body scrolls inside its own box and the slide
  scrolls vertically. Nothing overflows horizontally.
- **Mobile (390×844):** the page is continuous, one column. The probability chart uses `␣the`
  labels so no label wraps (an earlier `" France"` label wrapped). The base and assistant
  quotes stack. The OR-stake code lines wrap inside their blocks rather than scrolling, which
  also fixed an axe `scrollable-region-focusable` finding from the first run. The long
  revisions wrap. The document has no horizontal overflow.
- **No-JS:** every slide is visible as a continuous page, and the navigation stays hidden. The
  probability chart shows its authored percentages without bars. The post-training quotes are
  static HTML. All notes are collapsed and open natively.
- **Print:** light palette, one slide per page, navigation hidden. Every speaker-notes body
  prints in full, with no max-height or scroll box (`print.png`). The disclosure state is
  restored after print.
- **Reduced motion:** same as desktop. The deck has no animation, and check-page confirmed motion
  is suppressed under the 10 ms threshold.

## D2 · Factorization

- The slide shows the conditional `p(x_t | x_<t)` and defines both symbols. x_t is the token at
  position t. x_<t is x_1 … x_{t−1}, the whole context.
- The joint `p(x_1, …, x_T) = ∏_{t=1}^{T} p(x_t | x_<t)` is the chain rule, stated as an exact
  factorization of the joint distribution, not an approximation. Autoregression is presented as
  a modelling choice: one network computes every factor, and generation samples left to right.
  Both statements are correct.
- Boundaries: x_<1 is empty, with a BOS token in practice. EOS is in the vocabulary, so stopping
  is an outcome and the length T is modelled. Both are correct and match the tiny-LM lab, which
  shows `BOS` before the prompt.
- Notes: write the conditional on the board and keep it there. Write the product as the chain
  rule. Predict question: is the factorization lossy? (No.) The formulas are mono, about 2 rem
  for the conditional, readable at projector size in the laptop screenshot.

## D3 · Tokens, strawberry and the pivot

- `tokens` says the model reads integer IDs and shows GPT-2's ID for " strawberry", 41236. That
  ID is the single `prompt_tokens` entry in `next_token.json`, with the revision and date cited.
  The vocabulary size of 50,257 is GPT-2's.
- Qualification: the hedge callout says spelling is learned only indirectly, so letter counting
  is “hard for it, not impossible”. Nothing claims counting is impossible.
- `tokenizer-lab` warns that the lab's splits and IDs are illustrative and hand-written
  (“␣straw” + “berry”), which the lab itself states. It also notes that real GPT-2 keeps the
  word as one token. This stops students reading the lab's illustration as GPT-2's split.
- `strawberry` runs `demos/model/strawberry.md` as written: the 300-letter invented word with 146
  r's, five headless runs with tools off, then the pivot where the agent writes and runs
  `work/count_r.py`. The slide and notes cite the recorded 2026-10-11 results (claude-haiku-5-5
  wrong 2 of 5, gpt-6-luna wrong 4 of 5, off by up to 32), which match the runbook. They use the
  runbook's commands, its Claude Code or Codex choice (`--via`) and its replay fallback. The
  pivot is framed as the course thesis: give the mechanical part to code.

## D4 · Distribution, sampling and System 1

- `distribution` shows that one forward pass gives probabilities. GPT-2's top 5 after “The
  capital of France is” are computed as exp(logit − logsumexp) from the fixture: ␣the 8.5%,
  ␣now 4.8%, ␣a 4.6%, ␣France 3.2%, ␣Paris 3.2%. The top 20 hold 45.7% of the mass. I recomputed
  these from `next_token.json`.
- Formula `p = softmax(z/T)`. The text says T < 1 sharpens towards the top token, the argmax as
  T → 0, and T > 1 flattens. The sampler draws one token and appends it.
- System 1 is named on the slide (“one fixed pass through the network, with no extra passes for
  a harder token”). The notes qualify it: fixed for a given model, context and configuration,
  not constant latency, because a longer context makes each pass slower.
- `reproducibility`: sampling allows outputs to differ but does not guarantee it, since a peaked
  distribution repeats itself. A fixed seed or argmax reproduces locally, as in the tiny-LM lab.
  Even greedy decoding on shared servers can drift, because batching can change the order of
  floating-point additions; the next-token lab says the same. The slide claims neither CLI has a
  seed or temperature option. That carries an as-of date (2026-10-11) and the two CLI-reference
  URLs from the sampling runbook. The recorded spreads (5 of 5 and 4 of 5 distinct) match the
  runbook.
- `system-1` closes on “fixed compute per token” with the same qualification. It hands over to
  Act II: run the pass in a loop with tools, code and checks.

## D5 · Attention

- One concept slide (`attention`) uses the soft database lookup framing. A database returns the
  one value whose key matches. In attention, the query is scored against every earlier key and
  its own, softmax gives weights that sum to 1, and the output is the weighted average of the
  values. Formula `softmax(qKᵀ/√d)·V`, plus the scaled score q·k_i/√d.
- The text equivalent is the slide itself. The three-step process row (Query → Match keys →
  Blend values) is labelled HTML, not an image.
- Causality is tied back to p(x_t | x_<t). GPT-2 small has 12 layers × 12 heads, which matches
  `attention.json`.
- `attention-lab` is the next slide and links `labs/attention.html`. It asks students to move
  the query towards a key (drag or sliders) and watch the weight and output. They then raise or
  zero the scale s (hard lookup vs plain average), and in the GPT-2 panel focus “it” and change
  layer and head. These steps match the lab's controls and its “Try it” text.

## D6 · How a model is made

- `pretraining`: training minimizes −log p(x_t | x_<t), a code length; with arithmetic coding a
  better predictor is a better lossless compressor. The source is Delétang et al., arXiv
  2309.10668, and the claims stay within the abstract: predictors and lossless compressors are
  equivalent, and LLMs are strong general-purpose compressors. The hedge says “lossy compression
  of the training text” is our metaphor for what the weights keep, not the paper's result. The
  notes attribute the “lossy zip file of the internet” image to Karpathy's deep-dive video,
  which is linked in the title slide's notes.
- `post-training`: `[data-fixture-id="factual"]` shows the shared question (the item's `prompt`,
  not the chat-templated input) and two excerpts. The base excerpt is its first three non-empty
  lines, a contiguous run of the fixture text that includes “New Zealand is the second largest
  country in the world…”. The instruct answer is complete; it stopped with EOS. Both are
  labelled as excerpt or complete and recorded. The `.cite` gives both model IDs and full
  revisions, greedy decoding, max 48 new tokens, the date 2026-10-10, and that the instruct
  input used the chat template.
- Behaviour vs correctness: post-training teaches the format (answer, then stop), not a fact
  checker. The notes say the same weights could still produce the false line.
- `rlvr`: task with a checkable answer → sample attempts → a program scores each (1 or 0) →
  reinforce what passed. The hedge says the model learns to pass the checker, so a weak checker
  is gamed (Act V). It cites Tülu 3 (arXiv 2411.15124) for the term and DeepSeek-R1 (arXiv
  2501.12948) for rule-based rewards at scale.

## D7 · Limits and the OR stake

- `cutoff`: no vendor cutoff date appears, so none needs a source. The weights stop at a date, and
  the model may not know that date precisely. Context supplied at run time (files, docs, search,
  tool output) is part of x_<t and can carry newer facts.
- `hallucination`: pretraining rewards likely text, not true text, and there is no truth oracle in
  p(x_t | x_<t). So a false continuation is produced and reads the same way as a true one, as in
  the recorded New Zealand line. Structural susceptibility is kept distinct from certain error:
  models often get common facts right and can be taught to abstain, but any single answer can be
  wrong. The check must come from outside the model.
- `or-stake`: the slide is labelled Illustrative. The stated problem is least total cost.
  `h.changeObjectiveSense(highspy.ObjSense.kMinimize)` and `…kMaximize` differ only in the
  sense. The slide says both are equally fluent, both run, and only the first matches. The notes
  tie this to P00: `p00_model.py` sets kMinimize, and the P00 lab's `flipped-sense` variant
  reports 1085 “optimal” instead of 485 (`exercises/p00-lab/README.md`).
