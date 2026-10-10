# Tokenizer lab: review evidence

Agent review by the implementer, 2026-10-10. Reviewed files (sha256):

| File | Bytes | sha256 |
| --- | --- | --- |
| `../tokenizer.html` | 57,179 | `a7ca70415aeae7a3c2069da2bcc4e80fae54fea0ff4a73c235570102ec5f6b32` |
| `vendor/r50k_base.js` | 502,907 | `e95692224049d99b15601019c4b1cad61e3ff7b17d0870fe20e668bd82c15717` |
| `vendor/o200k_base.js` | 2,047,463 | `fbc7419f14fb3a1460b56b156b94adb3480ec375a1dd404b0d0bd807fbff97e1` |

Any edit to these files invalidates this review: re-review, then update the hashes here and the
page weight in `README.md`.

## Screenshots

Sources: `node tools/html-pages/check-page.mjs sessions/01-fundamentals/cursus/labs/tokenizer.html`
(PASS, 0 failed checks), plus a disposable Playwright script (since removed) that captured the
playground and the predict card in interaction states at 1440×900 and 390×844.

- **Desktop (1440×900):** masthead, then the predict card (two questions, Lock in / Reveal / Reset),
  then the playground: textarea and encoding fieldset side by side, the Characters and Tokens counts,
  the coloured piece chips, the ID list, and two help lines. Then the preset buttons, the comparison
  table, the amber "Why not Claude's tokenizer?" note, and the footer with the credit and page weight.
  Adjacent chips use four alternating backgrounds, all distinct from the panel; each ID has a
  bottom border in its chip's colour. No collisions.
- **Laptop (1280×720):** same layout; the table's three columns fit.
- **Mobile (390×844):** one column. The encoding fieldset stacks under the textarea, chips wrap
  inside their panel, and the preset buttons wrap. The comparison table scrolls horizontally inside
  its labelled, focusable `table-wrap` region (the MPS and Python texts are pre-formatted and wide);
  the document itself has no horizontal overflow (checker: "no horizontal document overflow" passes;
  measured overflow 0 px).
- **No-JS:** the predict answers are visible and the buttons disabled. A callout says the live
  tokenizer needs JavaScript; the chip and ID panels are empty; the counts show the authored values
  for the initial sentence (62 characters, 14 tokens in o200k_base). The comparison table, the note
  and the footer are fully present.
- **Print:** light palette, one column. Predict answers shown, buttons and status hidden, preset
  buttons hidden (the table carries their texts). Chips keep their soft backgrounds; the note keeps
  its amber rule.
- **Reduced motion:** identical to desktop; the page has no animation.
- **Both encodings (MPS preset):** o200k_base gives 18 tokens, with runs of spaces as single
  chips. Switching to r50k_base gives 40 tokens, almost one chip per space (ID 220). Whitespace is
  visible: whitespace-only chips show a `·` per space, `→` per tab and `↵` per new line (CSS marks;
  the chip's text stays the exact decoded piece). Leading spaces inside word pieces show as a gap
  within the chip's background.
- **Hover pair:** French preset in r50k_base, hovering the chip "ù": that chip and ID `117` both get
  a light outline; the neighbouring chips and IDs are unchanged. The chip before it (ID `127`) shows
  the ⋯ mark, because the first byte of "ù" decodes to no text on its own (explained under the chips).
  The test suite also checks hovering an ID, and arrow-key focus moving the highlighted pair.
- **Revealed prediction:** after Lock in and Reveal, each question shows "Correct." or "Not quite.
  The answer is …" and the answer blocks with IDs 101830 and 41236 and the three-r explanation.
- **2,000-character input:** 2,000 characters → 585 o200k_base tokens. Chips wrap (about six per
  line on mobile) inside a panel that scrolls vertically after 22rem; the ID panel scrolls after
  14rem. No page overflow at either width.

## Presets

Each preset's exact text (the button's `value`), and what it shows:

- `strawberry`: " strawberry" (leading space). One token in both encodings; sets up the r-counting question.
- `optimization`: "Optimization". 3 tokens in GPT-2, 1 in o200k_base: a larger vocabulary keeps whole words.
- `bonjour`: "Bonjour". 3 tokens in GPT-2, 1 in o200k_base: French gains the most from o200k_base.
- `latex`: `\sum_{j=1}^{n} a_{ij} x_j \le b_i`, a genuine LP constraint row (Σ_j a_ij x_j ≤ b_i) in LaTeX.
- `python`: a real two-line Python function computing a linear objective:

  ```python
  def objective(x):
      return sum(c * v for c, v in zip(costs, x))
  ```

- `number`: "123456789012345678901234567890", 30 digits. o200k_base cuts it into groups of three; GPT-2's groups are irregular.
- `mps`: `    x1        COST         1.0   LIM1         1.0`, a COLUMNS-section line of an MPS file in fixed-field layout: variable x1 has coefficient 1.0 in the objective row COST and in the constraint row LIM1.
- `french`: "Bonjour, où sont les contraintes du modèle ?", a natural French sentence (French spacing before "?"), with an accent GPT-2 splits into two byte tokens ("ù" → IDs 127, 117).

All counts and IDs in the static table were produced by the vendored encoders, and the test suite
re-checks them against independently loaded copies of the same files.

## Claude note

Verbatim text of `[data-tok-note]` (the same with and without JavaScript and in print):

> Why not Claude’s tokenizer? Claude’s tokenizer is not public, so this lab shows two public encodings instead: OpenAI’s o200k_base (GPT-4o family) and GPT-2’s r50k_base. Every tokenizer cuts the same text differently, so these counts are not Claude’s counts. To count Claude tokens, use Anthropic’s token counting API. Encoders: gpt-tokenizer 3.4.0. As of 2026-10-10.

Linked sources: <https://platform.claude.com/docs/en/build-with-claude/token-counting>
(Anthropic's token counting endpoint; fetched 2026-10-10, it counts tokens through the API and says
the count is an estimate) and <https://www.npmjs.com/package/gpt-tokenizer/v/3.4.0>.
The claim that Claude's tokenizer is not public is dated because it could change.
It does not claim how Claude's counts compare with these encodings.

## Vendoring provenance

Transcript, 2026-10-10, in a new empty temporary directory:

```text
$ npm pack gpt-tokenizer@3.4.0 --ignore-scripts --json
  "id": "gpt-tokenizer@3.4.0",
  "size": 17682451,
  "shasum": "4caa73edfdaa649f01dfa84f930e8a320ac0b1b1",
  "integrity": "sha512-wxFLnhIXTDjYebd9A9pGl3e31ZpSypbpIJSOswbgop5jLte/AsZVDvjlbEuVFlsqZixVKqbcoNmRlFDf6pz/UQ==",
  "filename": "gpt-tokenizer-3.4.0.tgz",
$ npm view gpt-tokenizer@3.4.0 dist.integrity dist.tarball
dist.integrity = 'sha512-wxFLnhIXTDjYebd9A9pGl3e31ZpSypbpIJSOswbgop5jLte/AsZVDvjlbEuVFlsqZixVKqbcoNmRlFDf6pz/UQ=='
dist.tarball = 'https://registry.npmjs.org/gpt-tokenizer/-/gpt-tokenizer-3.4.0.tgz'
$ sha256sum gpt-tokenizer-3.4.0.tgz
57004e95441a8aabc39296130c7263e9c5e440cee3f0b19111e561aefa3dada5  gpt-tokenizer-3.4.0.tgz
$ tar -xzf gpt-tokenizer-3.4.0.tgz
$ sha256sum package/dist/r50k_base.js package/dist/o200k_base.js package/LICENSE
e95692224049d99b15601019c4b1cad61e3ff7b17d0870fe20e668bd82c15717  package/dist/r50k_base.js
fbc7419f14fb3a1460b56b156b94adb3480ec375a1dd404b0d0bd807fbff97e1  package/dist/o200k_base.js
55c0b09ede96ed11bd312d90b200d74807cad56415cb491a76364e6a537d3b92  package/LICENSE
$ wc -c package/dist/r50k_base.js package/dist/o200k_base.js package/LICENSE
 502907 package/dist/r50k_base.js
2047463 package/dist/o200k_base.js
   1076 package/LICENSE
```

The committed `vendor/` files have the same hashes (byte-identical copies). Both scripts start with a
UMD wrapper (`"object"==typeof exports` / `define.amd` / `globalThis.GPTTokenizer_<encoding>`) and end
with `//# sourceMappingURL=<encoding>.js.map`; the `.map` files were not copied. The LICENSE is the
package's own MIT text (Copyright (c) 2023-2024 Bazyli Brzoska).

Version 4 check, same day: `npm pack gpt-tokenizer@4.0.0 --dry-run --json` lists only `LICENSE`,
`README.md`, `package.json`, `cjs/`, `esm/`, `data/` and `src/`, with no `dist/` UMD builds.

Upstream quirk found while vendoring: `decode()` shares one streaming `TextDecoder` per encoder, so a
token holding only the first bytes of a character decodes to an empty string and the bytes appear with
the next piece. The page decodes every token in order on each render, so its chips match a fresh
encoder's output, and it marks empty pieces with ⋯ and explains them.

## Performance

From the A1 latency test in `tools/html-pages/tests/tokenizer.test.mjs` on the reviewed page: real
keystrokes typed at the end of three 2,000-character corpora, timed from the `input` event to the
first animation frame where the chips, IDs and count are correct, after forced layout.
No CPU throttling, offline, `file://`.

- CPU: Intel(R) Core(TM) Ultra 9 285K
- OS: Linux 6.18.33.2-microsoft-standard-WSL2 (WSL2)
- Browser: Playwright Chromium 153.0.8010.12

| Corpus | Encoding | n | Median (ms) | Max (ms) |
| --- | --- | --- | --- | --- |
| prose | r50k_base | 20 | 12.8 | 13.2 |
| prose | o200k_base | 20 | 13.6 | 14.0 |
| code | r50k_base | 20 | 11.8 | 12.4 |
| code | o200k_base | 20 | 12.8 | 13.3 |
| numbers | r50k_base | 20 | 12.1 | 12.6 |
| numbers | o200k_base | 20 | 12.2 | 12.5 |

Most of each sample is the wait for the next frame. Typing at the end rebuilds only the changed tail
of the chip and ID lists. A full rebuild (switching encodings on 2,000 characters, 585 chips) measured
9–12 ms of script plus layout on this host. These are host timings, not a slower student laptop.
