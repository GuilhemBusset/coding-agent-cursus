# Attention lab: review evidence

Agent review by the implementer, 2026-10-11. Reviewed file: `../attention.html`,
124,623 bytes, sha256 `473ad94eb41fbe2fa830e0caf4370edc4f9f7bc4d1326832d0d87a2e416e7d6b`.
It embeds `../../fixtures/attention.json` verbatim (sha256
`2d935a6027668aa0aed745c01fa0829ccebdecdd099c0644a6b3f6a4f2380dac`).
Any edit to the page invalidates this review; re-review and update the hash.

## Screenshot review (all views)

Source: `node tools/html-pages/check-page.mjs sessions/01-fundamentals/cursus/labs/attention.html`
(PASS, 0 failed checks), plus a disposable Playwright script (deleted after use) that dragged the
query handle, pressed ArrowRight 60 times on the scale slider, then chose layer 1, head 1 and
clicked " tired", at 1440×900 and 390×844.

- **Desktop (1440×900):** the toy panel shows the key plot and the value plot side by side, both
  with tick labels from −2 to 2. Below them, the three sliders and Reset are on the left, and the
  measure table and output readout are on the right. Defaults: q = (1.00, 0.50) and
  s = 0.71 (equivalent d ≈ 1.98). Weights are 59.9%, 20.6%, 5.0% and 14.5%. The largest disc sits
  on v₁ and the amber output o = (0.89, −0.46) lies between v₁ and v₂. In the GPT-2 panel the
  13 chips fit on one line. Layer 5, head 4 is selected and " it" is the query, so its thick arc
  to " animal" (84.7%) dominates and the " animal" chip is tinted. The readout lists all nine
  causal weights with " animal" first. Nothing collides or overflows.
- **Laptop (1280×720):** same layout, slightly narrower. The sentence still fits on one line.
- **Mobile (390×844):** a single column. The plots fill the width, the sliders sit below them, and
  the table drops the score column so the four remaining columns fit without scrolling. The
  sentence sits in a bordered region that scrolls sideways, and a hint under it says so. On load
  that region is scrolled so the query " it" is centred, with its heavy arc running off to the
  left towards " animal". The document has no horizontal overflow; an earlier check-page run
  caught a 30 px table overflow, which the narrower `i` header and hidden score column fixed.
- **No-JS:** a callout explains that the draggable query, sliders and arcs need JavaScript and that
  the page is a static snapshot, linking `attention.json`. The plots are hidden. The table shows
  the default weights and the output (0.89, −0.46). The 13 chips are listed (disabled), with the
  default layer 5 / head 4 readout under them. Both notes are visible. No empty arc band is left
  above the chips, because that space is only reserved once the script runs.
- **Print:** light palette, one column. The plots print, Reset is hidden, and the arc overlay is
  hidden because it is positioned in screen pixels. The chips wrap, and the readout list carries
  the weights instead. Notes and provenance are visible.
- **Reduced motion:** identical to desktop. The lab has no animation. The toy SVG has no
  transitions; only the theme's short colour transition on buttons applies, and reduced motion
  disables it.
- **Dragged query, raised scale:** after dragging the handle up and to the left, the sliders read
  q = (−1.20, 1.55), and the scale readout reads s = 1.31 · equivalent d ≈ 0.58. The handle sits
  next to k₂. The table shows 0.5%, 91.8%, 7.6% and 0.0%. On the value plot almost all the disc
  area is on v₂, and o = (0.81, 1.45) sits just beside v₂. This is the hard-lookup end of the
  slider. At s = 0 the readout says "d → ∞: uniform average" and every weight is 25.0%.
- **Changed head, changed query:** with layer 1, head 1 and the query " tired", 12 arcs run back
  from " tired" to every earlier token. They nest by distance, so none merge into a band. There is
  a small self-loop, and the arc to " ." (a future token) is absent. The weights are spread out:
  The 18.8%, " tired" 14.1%, " animal" 10.6% and so on. That contrasts with the sharp
  coreference head, which is the point of the head selector. The layer and head stayed selected
  when the query changed. At 390 px the same state scrolls to " tired".

## Notes prose review

The two notes sit in their own section below both panels, one sentence each, with a `dt` label
outside the sentence.

> Without position information and without a causal mask, attention treats its inputs as a set, so permuting the tokens permutes the outputs the same way; GPT-2 breaks this on purpose with position embeddings and its causal mask.

Accurate. Self-attention computes each output as softmax(q_i·K/√d)·V, where every row depends on the
token at that position and on the *set* of all key/value rows. Reordering the inputs therefore
reorders the outputs identically: the map is permutation-equivariant, not invariant, and the
sentence says "permutes the outputs the same way" rather than "leaves them unchanged". GPT-2 adds
learned absolute position embeddings (`wpe`) to the token embeddings, and its causal mask makes
token i see only tokens 0..i. Either one alone breaks the symmetry, and the GPT-2 panel shows the
mask directly, since no arc ever goes to a later token.

> Each head has its own learned query, key and value projections, so it computes its own measure and expectation; GPT-2 small runs 12 heads in each of its 12 layers and concatenates their outputs before a final projection.

Accurate. In GPT-2's attention block, one fused `c_attn` matrix produces Q, K and V. These are split
into 12 heads of 64 dimensions (768 / 12), so each head effectively has its own projection slices.
Each head computes its own softmax weights (a measure over the earlier tokens) and its own
weighted average of its values. The 12 head outputs are concatenated back to 768 dimensions and
passed through the output projection `c_proj`. GPT-2 small has 12 layers with 12 heads each,
which matches the fixture's `layers` = 12 and `heads` = 12 and the 144 choices in the selectors.
"Measure and expectation" deliberately reuses the toy panel's vocabulary.

## Data handling

- The real panel shows each stored byte as raw/255 without applying softmax again or renormalizing.
  The caption says weights are rounded to multiples of 1/255, so a row's total can differ slightly
  from 100%.
- The default view picks the head that maximizes weights[layer][head][focus][referent]
  (" it" → " animal"), with the first maximum in layer-major order. That is layer 5, head 4
  (0-based 4, 3), at 216/255 = 84.7%.
- Provenance (model id, full revision, dtype, device, export date, generator) is rendered from the
  embedded `meta` block. The panel is labelled recorded, not illustrative. Only the toy panel
  carries the illustrative label.
