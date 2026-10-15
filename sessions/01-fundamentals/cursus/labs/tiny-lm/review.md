# Tiny LM lab: review evidence

Agent review by the implementer, 2026-10-10. Reviewed file: `../tiny-lm.html`,
1,500,681 bytes, sha256 `ba3a6a80191f9f4d4a308e5195527e883ba6aafd8f79edb90f60adda4d9129df`.
Any edit to the page invalidates this review; re-review and update the hash.

## Screenshot review (all views)

Source: `node tools/html-pages/check-page.mjs sessions/01-fundamentals/cursus/labs/tiny-lm.html`
(PASS, 0 failed checks), plus a disposable Playwright script that pressed Run and then rewound at
generated token 21, at 1440×900 and 390×844.

- **Desktop (1440×900):** two columns. Generator on the left (prompt, seed, Step, Run 40 tokens,
  Reset, the token stream and the status line), sampler on the right (top-10 chart, then the
  temperature and top-p sliders with their live formulas). After Run, 40 chips wrap in the
  stream. Nucleus rows are shaded with an accent rule, and their q column reads `q 36.1%`; the rest read `cut`.
  After the rewind, the struck-through "Previous branch" line sits under the stream. No collisions or overflow.
- **Laptop (1280×720):** same layout; the formula outputs wrap inside the right column.
- **Mobile (390×844):** a single column. Prompt and seed stack, chips wrap at about six per line, and
  the chart's four columns (label, bar, p, q) fit without horizontal scroll. Long formula text wraps.
- **No-JS:** caption, lede and controls are shown (disabled), with a notice that the model needs
  JavaScript. The chart shows the authored snapshot (the real distribution after "Once upon a time"
  at T = 1, top-p = 0.9: "," 96.9%, " there" 2.9%, …) with percentages as text. The bars are added
  by script, so they are absent here, which is acceptable.
- **Print:** light palette. Caption visible; buttons hidden; both disclosures ("The model in
  numbers" and the MIT licence text) are expanded; the layout is one column.
- **Reduced motion:** identical to desktop; the page has no animation.
- **Characters split across byte tokens:** the prompt "Tom said 你好 to", six Steps, then a rewind at
  generated token 2, at 1440×900 and 390×844. The tokenizer has no piece for 你 or 好, so each is three
  byte-fallback tokens. Each shows as an explicit byte label (`<0xE4><0xBD><0xA0><0xE5><0xA5><0xBD>`),
  not as a replacement character, and a "Read as UTF-8" line under the stream decodes the whole
  sequence across token boundaries: "Tom said 你好 to make Re". This equals `TinyLM.decode`. The
  previous-branch line gets the same joined reading when its tail holds such bytes. Both lines are
  hidden when no token is a byte above 0x7F, so the default view is unchanged. On mobile the labels wrap
  inside the stream box.

## Caption prose review

Caption on the page, under the lede, in an amber callout, present with and without JavaScript and in print:

> Trained only on TinyStories (short, simple children's stories), so this shows the mechanism, not the capability.

Plain words, one sentence, says what the data was and what not to conclude from the output. The
parenthesis explains TinyStories for students who do not know the dataset.

## Attribution and licence review

| Material | Source | Notice on the page |
| --- | --- | --- |
| Weights `stories260K.bin` | karpathy/tinyllamas at revision `0bd21da7…`, Andrej Karpathy | Footer: names the file, links the repo tree and the model card at that revision, and states MIT per the model card's `license: mit`. |
| Tokenizer `tok512.bin` | same repository and revision | Same footer paragraph. |
| Ported code (forward pass, encode, decode) | karpathy/llama2.c `run.c` at commit `350e04fe…`, Andrej Karpathy | Footer: links `run.c` and the repo at that commit and states MIT. The full MIT text is in a disclosure, byte-equal (after whitespace normalisation) to `reference/LICENSE`. |
| Sampler and UI | written for this course | Stated in the footer. llama2.js is acknowledged; none of its code is used. |

The model card carries no notice text of its own, so the page reproduces the llama2.c MIT notice,
which has the same author. The upstream LICENSE's copyright line reads "Copyright (c) 2023 Andrej"
(unchanged since the repository's first commit). It is vendored and shown verbatim, not
edited; the footer prose names Andrej Karpathy in full.

## Step forward-pass trace

Source trace of the reviewed page, backing "Step runs one forward pass" beyond the counters.

- `forward(model, s, token, pos)` (`../tiny-lm.html:12638`) runs the model for one token at one
  position against the KV cache in `s` and returns that position's logits.
- `stepOnce` (`../tiny-lm.html:12913-12916`) calls it exactly once, on the last token at
  `pos = tokens.length - 1`, then builds the distribution, makes one RNG draw and appends one token.
  Run (`generate`) and rewind call `stepOnce` once per token; rewind truncates the tail and
  regenerates from the kept prefix, whose cache entries are still valid because attention is causal.
- The prefill loop (`../tiny-lm.html:12900-12903`) forwards every prompt token except the last. It
  runs only in `startSession`: on page load, Reset, and a prompt or seed change, never inside Step.
- `TinyLM.logits` (`../tiny-lm.html:12834-12842`) calls the same `forward` on a fresh state, so the
  A1 parity test against llama2.c covers the function Step calls.

## Host timing (proxy, not the 2020 laptop)

From the A3 test in `tools/html-pages/tests/tiny-lm.test.mjs` on the reviewed page, taken from one
full passing run of `node tools/html-pages/tests/run-suite.mjs tools/html-pages/tests/tiny-lm.test.mjs`
on 2026-10-15. "Cold" is navigation start to first painted token, with Step clicked at
DOMContentLoaded. "Step" is the Step click to the painted token. Fresh browser context per trial,
offline, `file://`. All rows come from this one host.

- CPU: 12th Gen Intel(R) Core(TM) i7-1265U (a 2022 laptop CPU), 15 GB RAM visible to WSL2
- OS: Linux 6.6.87.2-microsoft-standard-WSL2 (WSL2)
- Browser: Playwright Chromium 153.0.8010.12

| CPU throttle | Trial | Cold (ms) | Step (ms) |
| --- | --- | --- | --- |
| 1× | 1 | 157.4 | 35.1 |
| 1× | 2 | 133.3 | 30.4 |
| 1× | 3 | 152.6 | 36.5 |
| 1× | 4 | 214.1 | 71.7 |
| 1× | 5 | 180.6 | 40.3 |
| 4× (CDP) | 1 | 731.5 | 104.4 |
| 4× (CDP) | 2 | 563.9 | 85.3 |
| 4× (CDP) | 3 | 529.5 | 103.3 |
| 4× (CDP) | 4 | 581.0 | 87.1 |
| 4× (CDP) | 5 | 629.3 | 162.4 |

All trials in this run are under 1000 ms. At native speed the margin is wide (about 130 to 215 ms
cold). Under 4× throttling it is narrower: cold trials are 530 to 730 ms here, and each Step stays
under 165 ms, so most of the cold time is loading the 1.5 MB page before Step runs, not the forward
pass. These are proxy numbers only.

The 4× margin is not reliable on this host. Over about 25 repeated runs of the A3 timing test
alone and 8 full-suite runs, on the same day and host with the page unchanged, the typical 4× cold
trial was 500 to 850 ms. But 7 of the isolated runs and 1 of the full-suite runs each had a single
4× cold trial over the limit (values recorded: 1032.9, 1199.1 and 1213.2 ms), which fails the test
and so the whole suite. Native-speed trials never came near the
limit. This proxy therefore says the page is close to the 1 s budget at 4× throttling, not
comfortably inside it.

## 2020 laptop (owner obligation, open)

Not done; no agent here has the hardware. Owner: on an identified physical 2020 laptop, open
`../tiny-lm.html` from `file://` in a fresh browser profile and record at least 10 fresh-load trials of
the default prompt (navigation to first painted token after Step, and Step to painted token).
All must be under 1000 ms. Record the hardware model, CPU, RAM, OS, browser and version, power state (battery or
mains), and the raw results here. Throttled or server numbers above do not count as this proof.
