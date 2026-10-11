# Act II deck: review evidence

Agent review by the implementer, 2026-10-11. Reviewed file: `../02-thinking.html`,
82038 bytes, sha256 `77d3c90a76623ce2209feb5f0d193f6f8789abe671d15b889ac298e60aa030f8`.
Any edit to the deck invalidates this review; re-review and update the hash and byte size.

Every source below was opened on 2026-10-11 while authoring, and each date was copied from the
source itself (arXiv submission line, Nature "Published", blog or press-release date line, the
OpenReview forum page via the Internet Archive, since openreview.net served a bot challenge).

## Checks run

- `node tools/html-pages/check-page.mjs sessions/01-fundamentals/cursus/02-thinking.html`:
  PASS, 0 failed checks (offline `file://`, shared-asset hashes, axe, deck navigation, every
  slide fits without internal scrolling at desktop and laptop sizes, no horizontal overflow at
  390 px, no-JS, reduced motion, print).
- `node tools/html-pages/tests/run-suite.mjs tools/html-pages/tests/thinking.test.mjs`: the full
  locked suite, all passing.
- `node tools/html-pages/tests/run-suite.mjs tools/html-pages/tests/components-tooling.test.mjs`:
  passes with `thinking` registered in `component-helpers.mjs` and `setup/package.json`.
- `uv run --locked pytest -q tests/test_pages.py tests/test_self_contained.py` in
  `sessions/01-fundamentals/`: 10 passed (all links relative and inside the session).

## Screenshot review

I opened the check-page screenshots and looked at each one.

- Desktop 1440×900, all 20 slides: one slide at a time, the collapsed "Speaker notes · N min"
  summary sits in the top-right corner, no collisions with the eyebrow or heading. Tables
  (effort dials, simulators) and the citations are legible.
- Laptop 1280×720, all 20 slides: the first pass had internal scrolling on `loop`,
  `effort-dials`, `addition-36-59` and `repo-model`. Fixed by compacting the process figures in
  paged mode, shortening the effort table's labels and the `repo-model` heading. Now every
  slide fits.
- Mobile 390×844: continuous page, columns stack. The first pass squeezed the effort table into
  one-word columns; the compact tables now keep a 34rem minimum width and scroll inside their
  labelled region, with no document overflow.
- No-JS: every slide visible in order, navigation hidden, notes collapsed but openable (native
  `details`), the effort-demo reveal collapsed with its summary visible.
- Print: every slide on its own page, notes and the recorded-results reveal expanded.
- Reduced motion: same as desktop; the deck has no animation of its own.
- Extra, with a disposable Playwright probe (deleted after use): opening the effort-demo reveal
  fits at 1280×720 and 1440×900 (the predict prompt and runbook give way to the results once the
  bets are in). An opened speaker-notes panel overlays the slide and scrolls inside itself.

## Timing plan (A2, agent half)

The `data-minutes` add up to 45: title 0.5, forward-pass 1, loop 2, system-1-2 2, cot-depth 2,
search 8 (lab and predict pause), rlvr 2, sharpen-or-expand 2, effort-dials 1, effort-demo 6,
overthinking 2, cot-faithfulness 2, addition-36-59 2, tool-cues 2, world-models 1,
internal-representations 2, kepler 3 and repo-model 3 (world-model lab, 6 in total),
simulators 1, wrap 0.5. This is a plan, not a measured delivery. The live rehearsal and
`02-thinking/rehearsal.md` remain the instructor's obligation; I did not write one.

## D2 · The loop, System 1 and System 2

- `forward-pass` restates Act I's handoff (there is no Act I deck in the repo to link): one
  pass through a fixed stack per token. The Merrill and Sabharwal abstract supports "simple
  problems … provably unsolvable by standard transformers that answer immediately"; the deck adds
  "under standard complexity assumptions", which is how those results are conditioned.
- `loop` matches Vaswani et al. §3 verbatim: "auto-regressive, consuming the previously
  generated symbols as additional input when generating the next". The serial-compute reading
  (pass n reads what pass n−1 wrote) follows directly. The advice is to budget the written
  tokens as compute; the notes tie it to the demo's price list, where output costs 5× input for
  both models (prices.json).
- `system-1-2`: Bengio's 2019 NeurIPS Posner lecture abstract says deep learning concentrated on
  System 1 tasks and that System 2 tasks are reasoning, planning, causality. LeCun 2022 §3.1
  names Mode-1 (a single pass through a policy module) and Mode-2 (planning through the world
  model, akin to model-predictive control) "by analogy" with Kahneman's System 1 and System 2.
- The caveat stays visible on the slide, not only in the notes: in a language model it is the
  same network in both modes, run for more tokens, so the words are a metaphor. The deck makes no
  claim about human cognition. The notes point out that LeCun's architecture has separate
  modules, which an LLM does not. The Driving line says to give room to work and to check the
  outcome, not the model's self-description.

## D3 · Chain of thought adds depth

Checked against Merrill and Sabharwal (arXiv 2310.07923, abstract). The slide says the fixed
network depth bounds the work in one pass and that each intermediate token buys another serial
decoding step. The three regimes are the abstract's: logarithmic steps add little, linear steps
recognize all regular languages (under the projected pre-norm assumption and standard complexity
conjectures, both named in the notes), polynomial steps give exactly polynomial-time problems
(with generalized pre-norm). The hedge box says this is a formal, theoretical result about
expressive power: it does not guarantee that a trained model finds the right chain, nor any
practical accuracy.

## D4 · Search, RLVR, sharpen or expand

- Coverage versus selection: Brown et al. (abstract) report coverage rising with samples over
  four orders of magnitude, turning into results where answers can be verified automatically,
  while majority vote and reward models plateau. The slide's "the cap is the verifier" and the
  Driving line (decide what selects the winner first) follow from that.
- Sequential versus parallel: Snell et al. §6 and Fig. 5 define both; easier questions did best
  with fully sequential revisions, harder ones with a mix (stated in the notes).
- R1-Zero versus R1, from the Nature article (published 2025-09-17): R1-Zero is RL on the
  DeepSeek-V3 base, bypassing SFT, with rule-based accuracy and format rewards that check only the
  final answer; AIME 2024 pass@1 rose from 15.6% to 77.9% during RL (Fig. 1a text); poor
  readability and language mixing; R1 is the multistage pipeline with rejection sampling, RL and
  SFT. The slide keeps the two apart.
- Sharpen or expand: both sides are attributed and dated. Yue et al. (2504.13837): RLVR wins at
  small k, base models win pass@k at large k, reasoning bounded by the base model. ProRL
  (2505.24864): prolonged RL with KL control and reference-policy resets beats the base model
  across pass@k, including tasks where the base fails at any number of attempts. The slide
  carries a visible Contested label; the ProRL abstract itself calls the question "contentious".

## D5 · Effort dials, the demo, overthinking

- Vendor table checked against the vendor documentation on 2026-10-11. Anthropic `effort`
  (platform.claude.com, "Effort levels"): low, medium, high, xhigh, max; Opus 5.5 defaults to
  medium; quote "a behavioral signal, not a strict token budget". `--effort` is the Claude Code
  flag used by the demo (README "Run"). OpenAI Codex `model_reasoning_effort`
  (developers.openai.com config reference): "such as low, medium, high, xhigh, max, or ultra.
  Available levels depend on the model and client." Google Gemini `thinking_level`
  (ai.google.dev "Controlling thinking" table): minimal, low, medium, high, by model.
- Demo models and date are not retyped from memory: `claude-opus-5-5` and `gpt-6-astra`,
  2026-10-11, as in `demos/effort/prices.json` and `recorded/results.json`; the suite checks the
  agreement.
- The recorded numbers in the effort-demo reveal (output tokens 783, 964, 467, 705; reasoning
  tokens 286, 447, 286, 516; seconds 9.9, 11.2, 18.6, 30.5; cost USD 0.0370, 0.0406, 0.0562,
  0.0681; all answers 229, correct) match `recorded/results.json`, rounded as in the README's
  "Expected outcome" table. The slide labels them as one dated sample: "one sample is an
  anecdote, not a rate".
- `overthinking` follows the demo. Chen et al. (2412.21187): o1-like models allocate excessive
  compute to simple problems with minimal benefit (title example 2+3). Gema et al. (2507.14417):
  four of the five failure modes from the abstract (distraction, overfitting to framings,
  spurious correlations, losing focus in deduction); the fifth, amplified concerning behaviours,
  is omitted as off-topic. The notes say the tasks were built to find the effect.

## D6 · Is the chain of thought the reasoning?

- `cot-faithfulness`, against the Anthropic post (2025-04-03): hint types (a Stanford professor,
  faux metadata, "unauthorized access"); mention rates averaged across hint types 25% (Claude 3.7
  Sonnet) and 39% (DeepSeek R1); in the reward-hacking setup the models exploited hints in over
  99% of cases and verbalized it in under 2% in most scenarios. The study's limits are on the
  slide: contrived multiple-choice tests, two model families, and the authors' note that harder
  tasks may force more of the real reasoning into the chain of thought. Contested label visible.
  The conclusion is "check evidence" (diff, commands, test run), not "traces are useless"; the
  notes say traces still help you notice problems.
- `addition-36-59`, against the Biology paper §Addition (2025-03-27): for 36 + 59 Claude 3.5
  Haiku runs a low-precision approximate pathway ("the sum is near 92") in parallel with exact
  ones-digit features (6 and 9 end in 5) and combines them into 95. Asked how, it gives the stated
  explanation of the school carry algorithm, quoted verbatim ("carried the 1"), which the
  attribution graph did not show; the paper's word is a lack of "metacognitive" insight. One
  model and one prompt: the notes call it a case, not a rate.
- `tool-cues`: I looked for a study that measures cues arriving through tool output changing an
  agent's behaviour while going unmentioned in its trace and did not find one. Following the
  design, the tool-output case on the slide is labelled illustrative and hypothetical (an invented
  README telling the agent to skip `legacy/` tests), with a Contested label stating it is an
  extrapolation. What is measured is cited: hints in the prompt (Anthropic, above) and indirect
  prompt injection through retrieved data (Greshake et al., 2302.12173, abstract). No numbers
  are invented.

## D7 · World models, three meanings

- `world-models` keeps three distinct meanings: an internal representation inside a network, a
  learned simulator used to predict and plan, and the agent's picture of your repo. The slide says
  evidence for one is not evidence for the others.
- Meaning 1: Othello-GPT (2210.13382, abstract): trained only on legal moves, an emergent
  nonlinear board-state representation, which interventions can use to control the output. Rhyme
  planning (Biology §Planning in Poems): "rabbit" and "habit" features active on the newline
  token before the line; suppressing "rabbit" switches the line to "habit".
- The limit: Vafa et al. (2507.06952, abstract): models trained on orbital trajectories fail to
  apply Newtonian mechanics on new physics tasks and behave like task-specific heuristics. The
  lab panel is an illustrative, stylized analogy (the lab says so); the slide and notes repeat it.
- Meaning 2, each with a dated official source: V-JEPA 2 (2506.09985, 2025-06-11); Genie 3
  (DeepMind blog, 2025-08-05: 24 fps, 720p, consistent for a few minutes); Cosmos 3 (NVIDIA press
  release, 2026-05-31); AMI Labs (launch update, 2026-03-10). AMI Labs' aims are stated as goals
  ("Goal, not a product"), from its homepage and launch post. The table carries a Contested label:
  makers' announcements, not independent evaluations.
- Meaning 3: `repo-model` maps the closed loop to belief (repo picture), act, observe (test
  output) and replan, citing LeCun 2022 §3 and §3.1 (world model adjusted once the next
  observation is available; Mode-2 as model-predictive control). The planner panel is labelled
  illustrative; at its defaults the open loop misses and the closed loop reaches the goal
  (world-model lab review).

## A1 · Claim inventory

One row per recent factual claim in slide text, tables, diagrams, reveals and notes, plus the
older sources the deck links. "Contested" follows the deck's visible labels.

| Slide | Claim | Date | Source URL | Source section | Contested | Outcome |
| --- | --- | --- | --- | --- | --- | --- |
| forward-pass | Transformers that answer immediately cannot solve some simple problems such as graph connectivity (under standard complexity assumptions) | 2023-10-11 | https://arxiv.org/abs/2310.07923 | Abstract, first sentence | no | Supported; the hedge reflects the conjecture-based results the abstract cites |
| loop | Each generated token is consumed as input for the next step | 2017-06-12 | https://arxiv.org/abs/1706.03762 | §3 Model Architecture | no | Supported, quoted verbatim |
| loop | Speaker notes: output tokens cost 5 times input tokens for claude-opus-5-5 ($4 / $20 per million) | 2026-10-11 | https://platform.claude.com/docs/en/about-claude/pricing | prices.json `anthropic.models.claude-opus-5-5` | no | Matches prices.json (20 / 4 = 5); dated in a notes `.cite` |
| loop | Speaker notes: output tokens cost 5 times input tokens for gpt-6-astra ($10 / $50 per million) | 2026-10-11 | https://platform.openai.com/docs/pricing | prices.json `openai.models.gpt-6-astra` | no | Matches prices.json (50 / 10 = 5); dated in a notes `.cite` |
| system-1-2 | Bengio: deep learning mostly did System 1 tasks; System 2 is reasoning, planning, causality | December 2019 | https://neurips.cc/virtual/2019/invited-talk/15488 | Posner lecture abstract | no | Supported, paraphrase of the abstract |
| system-1-2 | LeCun: Mode-1 is a single pass through a policy, Mode-2 plans through a world model, both by analogy with Kahneman | 2022-06-27 | https://openreview.net/forum?id=BZ5a1r-kVsf | v0.9.2 §3.1 and §3.1.3 | no | Supported; "by analogy" is LeCun's wording |
| cot-depth | Log steps add little, linear steps recognize regular languages, polynomial steps give exactly P (under assumptions) | 2023-10-11 | https://arxiv.org/abs/2310.07923 | Abstract | no | Supported; assumptions named in notes |
| search | Coverage rises with samples over four orders of magnitude; verifiable domains convert it; vote and reward models plateau | 2024-07-31 | https://arxiv.org/abs/2407.21787 | Abstract | no | Supported |
| search | Parallel vs sequential revisions; best mix depends on prompt difficulty | 2024-08-06 | https://arxiv.org/abs/2408.03314 | §6, Fig. 5 and the difficulty-bin analysis | no | Supported |
| search | Best-of-N panel predict question and sliders (N up to 1,024, false-positive rate) | 2026-10-11 | sessions/01-fundamentals/cursus/labs/test-time-compute.html | Panel 1 | no | Matches the lab markup; panel is an illustrative simulation |
| rlvr | R1-Zero: RL from the V3 base without SFT, rule-based accuracy and format rewards on the final answer | 2025-09-17 | https://www.nature.com/articles/s41586-025-09422-z | Main text, DeepSeek-R1-Zero section | no | Supported |
| rlvr | Longer answers with verification and reflection; AIME 2024 pass@1 from 15.6% to 77.9% | 2025-09-17 | https://www.nature.com/articles/s41586-025-09422-z | Fig. 1a description | no | Supported |
| rlvr | R1-Zero readability and language mixing; R1 adds rejection sampling and SFT around RL | 2025-09-17 | https://www.nature.com/articles/s41586-025-09422-z | Introduction | no | Supported |
| sharpen-or-expand | RL wins pass@1, base wins pass@k at large k; reasoning bounded by the base model | 2025-04-18 | https://arxiv.org/abs/2504.13837 | Abstract | yes | Supported as the authors' claim, labelled contested |
| sharpen-or-expand | Prolonged RL with KL control and resets beats the base across pass@k, even where the base never succeeds | 2025-05-30 | https://arxiv.org/abs/2505.24864 | Abstract | yes | Supported as the authors' claim, labelled contested |
| sharpen-or-expand | The question is open as of the session date | 2026-10-11 | https://arxiv.org/abs/2505.24864 | Abstract, "it remains contentious" | yes | Our judgment, visibly labelled |
| effort-dials | Claude effort levels low to max; Opus 5.5 defaults to medium; "a behavioral signal, not a strict token budget" | 2026-10-11 | https://platform.claude.com/docs/en/build-with-claude/effort | How effort works; Effort levels | no | Checked on the page 2026-10-11 |
| effort-dials | Codex model_reasoning_effort, levels advertised per model | 2026-10-11 | https://developers.openai.com/codex/config-reference | model_reasoning_effort entry | no | Checked on the page 2026-10-11 |
| effort-dials | Gemini thinking_level: minimal, low, medium, high, by model | 2026-10-11 | https://ai.google.dev/gemini-api/docs/thinking | Controlling thinking table | no | Checked on the page 2026-10-11 |
| effort-dials | Demo models claude-opus-5-5 and gpt-6-astra; Claude Code flag --effort | 2026-10-11 | sessions/01-fundamentals/cursus/demos/effort/prices.json | models; README Run section | no | Matches prices.json, results.json and the README |
| effort-demo | Recorded tokens, seconds, costs; all four runs answered 229, correct | 2026-10-11 | sessions/01-fundamentals/cursus/demos/effort/recorded/results.json | runs | no | Matches the recording, rounded as in the README table |
| effort-demo | Recorded with Claude Code 2.1.296 and codex-cli 0.162.1; offline replay fallback command | 2026-10-11 | sessions/01-fundamentals/cursus/demos/effort/README.md | Recording; Fallback | no | Matches |
| effort-demo | Notes: high effort cost about 1.1 to 1.2 times low | 2026-10-11 | sessions/01-fundamentals/cursus/demos/effort/README.md | Expected outcome | no | Matches the cost ratios |
| overthinking | o1-like models overthink simple problems with minimal benefit | 2024-12-30 | https://arxiv.org/abs/2412.21187 | Title and abstract | no | Supported |
| overthinking | Longer reasoning lowered accuracy: distraction, framing overfit, spurious correlations, lost focus | 2025-07-19 | https://arxiv.org/abs/2507.14417 | Abstract, failure modes 1 to 4 | no | Supported; mode 5 omitted |
| overthinking | In the recorded demo high effort bought no correctness, only cost | 2026-10-11 | sessions/01-fundamentals/cursus/demos/effort/recorded/results.json | runs | no | Supported for this single sample |
| cot-faithfulness | Hint types; hints mentioned 25% (Claude 3.7 Sonnet) and 39% (DeepSeek R1) of the time | 2025-04-03 | https://www.anthropic.com/research/reasoning-models-dont-say-think | Main results | yes | Supported, labelled contested |
| cot-faithfulness | Reward hacks exploited in over 99% of cases, admitted under 2% in most scenarios | 2025-04-03 | https://www.anthropic.com/research/reasoning-models-dont-say-think | Faithfulness and reward hacking | yes | Supported |
| cot-faithfulness | Limits: contrived multiple choice, two model families, harder tasks may differ | 2025-04-03 | https://www.anthropic.com/research/reasoning-models-dont-say-think | Limitations paragraph | yes | Supported |
| addition-36-59 | Approximate pathway ("near 92") in parallel with ones-digit features, combined into 95 | 2025-03-27 | https://transformer-circuits.pub/2025/attribution-graphs/biology.html | §Addition | no | Supported |
| addition-36-59 | Stated explanation describes carrying the 1, unlike the traced computation | 2025-03-27 | https://transformer-circuits.pub/2025/attribution-graphs/biology.html | §Addition, quoted dialogue | no | Supported, quoted verbatim |
| tool-cues | Instructions planted in retrieved data steer LLM-integrated applications | 2023-02-23 | https://arxiv.org/abs/2302.12173 | Abstract | no | Supported |
| tool-cues | Cues arriving through tool output may go unmentioned; README case | 2025-04-03 | https://www.anthropic.com/research/reasoning-models-dont-say-think | Setup (hints placed in the prompt) | yes | No direct study found; the case is labelled illustrative and hypothetical |
| world-models | Three meanings of "world model" kept distinct | 2022-06-27 | https://openreview.net/forum?id=BZ5a1r-kVsf | §3 world model module | no | Framing by the deck; meanings 1 and 2 illustrated by the cited works |
| internal-representations | Othello-GPT holds a nonlinear board-state representation that interventions can use | 2022-10-24 | https://arxiv.org/abs/2210.13382 | Abstract | no | Supported |
| internal-representations | Rhyme candidates "rabbit" and "habit" active at the newline; suppression switches to "habit" | 2025-03-27 | https://transformer-circuits.pub/2025/attribution-graphs/biology.html | §Planning in Poems | no | Supported |
| kepler | Trained on orbits, predicts well, fails to apply Newtonian mechanics on new tasks | 2025-07-09 | https://arxiv.org/abs/2507.06952 | Abstract | no | Supported; lab panel labelled illustrative |
| simulators | V-JEPA 2 action-conditioned model plans robot pick-and-place toward image goals | 2025-06-11 | https://arxiv.org/abs/2506.09985 | Abstract | yes | Supported as the authors' claim |
| simulators | Genie 3: interactive worlds from text, 24 fps, 720p, consistent for a few minutes | 2025-08-05 | https://deepmind.google/blog/genie-3-a-new-frontier-for-world-models/ | Opening paragraph | yes | Supported as the maker's claim |
| simulators | Cosmos 3: open world foundation model with vision reasoning, world generation, action prediction | 2026-05-31 | https://nvidianews.nvidia.com/news/nvidia-launches-cosmos-3-the-open-frontier-foundation-model-for-physical-ai | Lead paragraph | yes | Supported as the maker's claim |
| simulators | AMI Labs aims at world models predicting in representation space and planning; launched with a $1.03B round | 2026-03-10 | https://amilabs.xyz/updates | Official launch update; homepage aims | yes | Stated as goals, not a product |
| repo-model | World model adjusted once the next observation is available; Mode-2 as model-predictive control | 2022-06-27 | https://openreview.net/forum?id=BZ5a1r-kVsf | §3 and §3.1 | no | Supported |
| repo-model | Planner panel: at default model error the open loop misses and the closed loop reaches the goal | 2026-10-11 | sessions/01-fundamentals/cursus/labs/world-model.html | Planner panel; labs/world-model/review.md | no | Matches the lab review; illustrative simulation |
