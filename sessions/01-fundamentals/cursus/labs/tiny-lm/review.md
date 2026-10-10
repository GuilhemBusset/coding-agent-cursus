# Tiny LM lab: review evidence

Agent review by the implementer, 2026-10-10. Reviewed file: `../tiny-lm.html`,
1,499,132 bytes, sha256 `994fb5007b072ab391129d76948b930971ac5db865cff8567bd68cf90c4a46dc`.
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

## Host timing (proxy, not the 2020 laptop)

From the A3 test in `tools/html-pages/tests/tiny-lm.test.mjs` on the reviewed page. "Cold" is
navigation start to first painted token, with Step clicked at DOMContentLoaded. "Step" is the Step
click to the painted token. Fresh browser context per trial, offline, `file://`.

- CPU: Intel(R) Core(TM) Ultra 9 285K
- OS: Linux 6.18.33.2-microsoft-standard-WSL2 (WSL2)
- Browser: Playwright Chromium 153.0.8010.12

| CPU throttle | Trial | Cold (ms) | Step (ms) |
| --- | --- | --- | --- |
| 1× | 1 | 63.0 | 12.5 |
| 1× | 2 | 62.0 | 14.7 |
| 1× | 3 | 58.1 | 11.2 |
| 1× | 4 | 56.9 | 11.2 |
| 1× | 5 | 62.8 | 16.4 |
| 4× (CDP) | 1 | 236.7 | 44.4 |
| 4× (CDP) | 2 | 225.0 | 41.1 |
| 4× (CDP) | 3 | 231.6 | 40.7 |
| 4× (CDP) | 4 | 236.6 | 37.4 |
| 4× (CDP) | 5 | 234.8 | 40.3 |

All trials are under 1000 ms, by more than 4× even under 4× throttling. These are proxy numbers only.

## 2020 laptop (owner obligation, open)

Not done; no agent here has the hardware. Owner: on an identified physical 2020 laptop, open
`../tiny-lm.html` from `file://` in a fresh browser profile and record at least 10 fresh-load trials of
the default prompt (navigation to first painted token after Step, and Step to painted token).
All must be under 1000 ms. Record the hardware model, CPU, RAM, OS, browser and version, power state (battery or
mains), and the raw results here. Throttled or server numbers above do not count as this proof.
