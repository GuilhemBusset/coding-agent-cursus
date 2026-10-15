# Next-token lab: review evidence

Agent review by the implementer, 2026-10-10. Reviewed file: `../next-token.html`,
86,006 bytes, sha256 `78060a0adba8245206297ea2231d70542f9cce734fc35ccbffb3fc57bbd69d55`.
Any edit to the page invalidates this review; re-review and update the hash.

## Screenshot review (all views)

Source: `node tools/html-pages/check-page.mjs sessions/01-fundamentals/cursus/labs/next-token.html`
(PASS, 0 failed checks), plus a disposable Playwright script (deleted after use). It locked guesses on
"Thank you very" and on "The best thing about learning is", pressed Reveal, set T = 1.40 and
top-p = 0.85 with the keyboard, then pressed Sample ×100 in Sample mode and again in Argmax mode, at 1440×900 and 390×844.

- **Desktop (1440×900):** two columns. "Place your bets" is on the left: Previous and Next, "Prompt 1 of 20",
  the category label, the prompt in a mono box with a caret, the prompt's GPT-2 tokens as chips, the guess field
  with Lock guess, help text, Reveal and the class tally. On the right, "What GPT-2 assigned" shows only the
  placeholder sentence. No percentage is visible before Reveal.
- **Laptop (1280×720):** same layout; the prompt wraps inside the left column.
- **Mobile (390×844):** a single column. The first check-page run failed here with 163 px of horizontal overflow:
  the prompt-token chips had no break opportunity between them. They are now `inline-block` and wrap, and the
  re-run is clean. The carousel buttons sit side by side with the status below. In the revealed state the
  four-column sampling rows (token, bar, q, kept/cut) fit without horizontal scroll.
- **No-JS:** the noscript callout reads "The prompt carousel, guesses and sampling panel need JavaScript" and links
  `next_token.json`. All controls are disabled. The authored first prompt and an empty tally show, and both
  charts stay hidden.
- **Print:** light palette. The carousel, form, Reveal, Reset tally and Sample buttons are hidden. The layout is one
  column, and the prompt, its tokens and the tally remain.
- **Reduced motion:** identical to desktop. The page has no animation.
- **Revealed state:** each locked guess gets a verdict. Examples: "␣much → rank 1"; "much → rank 4"; for the spaced guess
  "  much  " (shown as "␣ much"), "→ spaces ignored: ␣much at rank 1, much at rank 4"; "banana → not in the top 20". Guessed rows are bold and highlighted in
  the real chart. After the 20 rows, an "All other tokens" row gives the rest of the mass (0.1% for the idiom prompt,
  22.3% for the open-ended one), and the coverage sentence repeats both numbers. The tally then shows the rank-1 and
  top-5 hits and the most common guesses. Guess entry and Lock are disabled.
- **Sampled state:** on the open-ended prompt at T = 1.40 and top-p = 0.85, 13 rows are shaded and labelled "kept"
  and 7 are labelled "cut" with 0.0%. The readout says "Kept 13 of 20 candidates. Before renormalizing they held
  85.8% of the sandbox mass at T = 1.40." The 100-draw histogram spread over 12 tokens with counts as text
  ("32 draws", …). In Argmax mode all 100 land on ␣that. On the idiom prompt, top-p = 0.85 keeps only ␣much, so
  Sample ×100 gives 100 draws of it: a useful peaked contrast.

## Prose review

Reproducibility note, under the decoding controls, in an amber callout:

> Why two runs differ: in Sample mode every draw uses fresh randomness, so pressing the button again gives different counts, and hosted chat products generally do not let you fix the random seed. Even greedy decoding on shared GPU servers can drift, because batching changes the order of floating-point additions and nudges the logits. Argmax here is deterministic: the same 20 stored logits always give the same token.

Assessment: it names the two separate causes (sampling randomness, and floating-point non-associativity under
server batching) without vendor-specific or dated claims, so no as-of date is needed. It ends by contrasting
with the page's own deterministic Argmax, which students can check right away by pressing Sample ×100 twice in each mode.

Sandbox and coverage sentence, at the top of the sampling panel:

> The fixture stores only GPT-2's 20 largest logits, so the full-vocabulary tempered softmax cannot be recomputed here. This sandbox applies softmax(z/T) to the 20 shown candidates, renormalized among them, then cuts with top-k and top-p.

Assessment: it states the limit before any slider is touched, so the sandbox numbers are not read as GPT-2's own
tempered probabilities. The real full-vocabulary values stay in the separate Reveal chart, with the uncovered mass
shown as "All other tokens". The order of operations is spelled out in the help line under the sliders.
