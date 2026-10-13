# Tokenizer lab: review evidence

Agent review by the implementer, 2026-10-13 (attempt 3, re-reviewed after redesign 1 re-locked the checks; the page was amended earlier for:
GPT-2 default, four-choice predict questions, `␣` marks on every space, chip borders and labels,
the "Across encodings" disclosure with token pieces, and a dated note that says these IDs are not
Claude's). Reviewed files (sha256):

| File | Bytes | sha256 |
| --- | --- | --- |
| `../tokenizer.html` | 62,557 | `b0b4764be3e0f8e0ddaa22a73661f7b0bf9626f6d3f7ab6a4ac42c6bb8e5b030` |
| `vendor/r50k_base.js` | 502,907 | `e95692224049d99b15601019c4b1cad61e3ff7b17d0870fe20e668bd82c15717` |
| `vendor/o200k_base.js` | 2,047,463 | `fbc7419f14fb3a1460b56b156b94adb3480ec375a1dd404b0d0bd807fbff97e1` |

Any edit to these files invalidates this review: re-review, then update the hashes here and the
page weight in `README.md`.

## Screenshots

Sources: `node tools/html-pages/check-page.mjs sessions/01-fundamentals/cursus/labs/tokenizer.html --output artifacts/html-pages/tokenizer`
(2026-10-13, on the reviewed hash above: PASS, 0 failed checks; every view screenshot in that
directory looked at), the screenshots the test suite writes there (`tokenizer-predict-revealed.png`,
`tokenizer-grouped-hover-chip.png`, `tokenizer-grouped-hover-id-0.png`, `tokenizer-grouped-hover-id-1.png`),
and disposable Playwright scripts kept outside the repo that wrote `extra-*.png` at 1440×900 and
390×900 into the same directory. Files in that directory without these names are left over from
earlier attempts and were not used.

- **Desktop (1440×900):** masthead, then the predict card above the playground (two questions with four choices each, Lock in / Reveal / Reset), then the playground: textarea beside the Encoding fieldset with GPT-2 (r50k_base) checked, "Characters (Unicode code points) 62" and "Tokens 15", the piece chips, the ID strip and two help lines. Then the eight preset buttons, the closed "Across encodings" disclosure, the amber Claude note and the footer with credit and page weight.
- **Laptop (1280×720):** same layout as desktop; the first question's legend fits on one line and the encoding fieldset stays beside the textarea.
- **Mobile (390×844):** one column; the encoding fieldset stacks under the textarea, the counts stack, chips and IDs wrap inside their panels, preset buttons wrap in two per row, and the document has no horizontal overflow.
- **No-JS:** both predict answers are visible with the buttons disabled; a callout says the live tokenizer needs JavaScript; the chip and ID panels are empty; the counts show the authored 62 and 15; presets, disclosure, Claude note and footer are present.
- **Print:** light palette, one column; predict answers shown; preset buttons hidden; the "Across encodings" table is printed open with the pieces of the three words as bordered boxes; the note keeps its amber rule.
- **Reduced motion:** identical to desktop, since the page has no animation or transition to suppress.
- **Whitespace and both encodings:** the default sentence in r50k_base shows `␣read`, `␣numbers`, and so on, so every space is a visible `␣` mark (CSS; the chip text stays the exact piece). The Python preset in r50k_base (`extra-python-whitespace-1440.png`) shows `↵` for the new line and three separate `␣` chips for the indent (ID 220 each); o200k_base keeps runs of spaces in fewer chips. Every chip has a `--rule` border as well as one of four tints, so neighbours are distinguishable without colour.
- **Multi-token emoji and French chips:** "🍓🍓 日本語 — Ça coûte 3 € — où ?" in o200k_base (`extra-emoji-hover-id-1440.png`, `extra-emoji-hover-id-390.png`) gives 15 tokens in 13 chips; each 🍓 is one grouped chip with a dashed ×2 badge over IDs `102415 241`. The French preset in r50k_base (`extra-french-r50k-*.png`) shows "ù" as one ×2 chip. The badges stay legible at both widths.
- **Hover from the chip side:** hovering the first 🍓 chip fills it with the accent colour and outlines it, together with both of its IDs `102415` and `241`; the neighbouring chips and IDs are unchanged (`extra-emoji-hover-chip-viewport-1440.png`; the suite's `tokenizer-grouped-hover-chip.png` shows the same on its own string).
- **Hover from the ID side:** hovering ID `241` (index 1) fills that ID and its 🍓 chip, but not the sibling ID `102415` (`extra-emoji-hover-id-1440.png`, and the suite's `tokenizer-grouped-hover-id-*.png`). An element screenshot first captured the chip-side hover cleared because the capture scrolled the page under the pointer; the DOM showed the link active, and a viewport capture confirms it.
- **Revealed prediction:** after Lock in and Reveal by keyboard (`tokenizer-predict-revealed.png`), each question shows "Correct." and the answer blocks with IDs 41236 (r50k_base) and 101830 (o200k_base) and the three-r explanation.
- **Long number:** the number preset in r50k_base (`extra-number-r50k-390.png`) shows 14 chips (123, 45, 67, 89, 01, …) that wrap onto two lines inside the panel at 390 px, with no overflow.
- **2,000-character input:** a 2,000-character mixed text (French, English, 🍓, digits, unbroken letters) in r50k_base gives 854 tokens (`extra-2000-character-*.png`). Chips wrap (about six per line on mobile) inside a panel that scrolls vertically after 22rem, and the ID panel scrolls after 14rem. There is no document overflow at 1440 or 390 px (measured `scrollWidth` ≤ `innerWidth`).

## Presets

Each preset's exact text (the button's `value`), and what it shows:

- `strawberry`: " strawberry" (leading space). One token in both encodings (41236, 101830); it sets up the r-counting question.
- `optimization`: "Optimization". GPT-2 gives 3 tokens ("Opt", "im", "ization"), o200k_base 1: a larger vocabulary keeps whole words.
- `bonjour`: "Bonjour". GPT-2 gives 3 tokens ("Bon", "j", "our"), o200k_base 1.
- `latex`: `\sum_{j=1}^{n} a_{ij} x_j \le b_i`, a genuine LP constraint row (Σ_j a_ij x_j ≤ b_i) in LaTeX.
- `python`: a real two-line Python function computing a linear objective:

  ```python
  def objective(x):
      return sum(c * v for c, v in zip(costs, x))
  ```

- `number`: "123456789012345678901234567890", 30 digits. o200k_base cuts it into groups of three; GPT-2's groups are irregular.
- `mps`: `    x1        COST         1.0   LIM1         1.0`, a COLUMNS-section line of an MPS file in fixed-field layout: variable x1 has coefficient 1.0 in the objective row COST and in the constraint row LIM1.
- `french`: "Bonjour, où sont les contraintes du modèle ?", a natural French sentence (French spacing before "?"), with an accent that GPT-2 splits into two byte tokens ("ù" → IDs 127, 117).

The counts, IDs and pieces in the "Across encodings" table were produced by the vendored encoders
through the stateless byte path, and the test suite re-checks every cell against independently
loaded copies of the same files.

## Claude note

Verbatim text of `[data-tok-note]` (the same with and without JavaScript and in print):

> Why not Claude’s tokenizer? Claude’s tokenizer is not public (as of 2026-10-13), so this page uses OpenAI’s encodings: GPT-2’s r50k_base and GPT-4o’s o200k_base. These IDs are not Claude’s, and Claude’s counts differ. Anthropic offers an online token counting endpoint: it counts tokens for a message, but it does not publish a tokenizer or its IDs. Sources: gpt-tokenizer 3.4.0, which reimplements OpenAI’s tiktoken encodings.

Judgement: accurate. It says plainly that the IDs on the page are not Claude's, and it names
both encodings. It separates Anthropic's online counting endpoint
(<https://platform.claude.com/docs/en/build-with-claude/token-counting>: an API call that returns a
token count for a message) from a public tokenizer: the endpoint gives counts, not a vocabulary or
IDs. "Not public" is dated, because it could change. "Claude's counts differ" is stated as a general
property of a different vocabulary; the page gives no figure for how large the difference is. The
other links are gpt-tokenizer 3.4.0 on npm and OpenAI's tiktoken repository, the source of the
r50k_base and o200k_base definitions.

## Strawberry prediction explanation

Verbatim revealed answers (the same text shows without JavaScript):

> One token in both encodings. In GPT-2’s r50k_base, “ strawberry” is the single ID 41236; in o200k_base it is the single ID 101830. Both decode back to the whole piece “ strawberry”. The leading space belongs to the token. Without it, “strawberry” splits into three pieces, “st”, “raw”, “berry”, in both encodings.

> The text has three r's, but the model receives one integer, 41236 in r50k_base (or 101830 in o200k_base), not the letters s-t-r-a-w-b-e-r-r-y. It can learn letter facts only indirectly, from training text that happens to spell out what an ID contains. That is why counting letters is unreliable, and why the dependable move is to have the model write code that counts them.

Judgement: accurate. The IDs and pieces match the vendored encoders, and the suite checks them
against the oracle. The explanation keeps the three literal r's in the text separate from what the
model receives, a single ID. It says letter knowledge is learned indirectly and that counting is
unreliable, not impossible, and it points to the tool-use pivot (write code that counts) that the
session demo uses. It does not claim that any particular model gets the count wrong.

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

Re-verified 2026-10-13 with registry access: `npm view gpt-tokenizer@3.4.0 dist.integrity dist.tarball`
returned the same integrity and tarball URL; a fresh `npm pack gpt-tokenizer@3.4.0 --ignore-scripts`
in a new empty directory produced a tarball with the same sha256, whose sha512 recomputed with
`openssl dgst -sha512 -binary | base64` equals the integrity. `cmp` reports the three extracted files
byte-identical to the committed `vendor/` files.

Both scripts start with a UMD wrapper (`"object"==typeof exports` / `define.amd` /
`globalThis.GPTTokenizer_<encoding>`) and end with `//# sourceMappingURL=<encoding>.js.map`; the
`.map` files were not copied. The LICENSE is the package's own MIT text (Copyright (c) 2023-2024
Bazyli Brzoska).

Version 4 check, 2026-10-10: `npm pack gpt-tokenizer@4.0.0 --dry-run --json` lists only `LICENSE`,
`README.md`, `package.json`, `cjs/`, `esm/`, `data/` and `src/`, with no `dist/` UMD builds.

Upstream quirk found while vendoring: `decode()` shares one streaming `TextDecoder` per encoder and
never flushes it, so bytes left by one call leak into the next. The page therefore never calls
`decode()`. It reads each token's string or bytes from the rank table
(`bytePairEncodingCoreProcessor.tryDecodeToken`), groups the tokens of a split character, and
decodes each group with a fresh, non-streaming `TextDecoder` (see README "How the page turns IDs
into chip text").

## Performance

Measured 2026-10-13 by the locked A1 latency test itself
(`node tools/html-pages/tests/run-suite.mjs tools/html-pages/tests/tokenizer.test.mjs`, test 13,
after the amendment that sets the first input as `textarea.value` plus one bubbling `input` event)
on the reviewed page. Four 2,000-code-point corpora, each under both starting encodings, a fresh
page per run, offline over `file://`, no CPU throttling. Each run records one first input, one
encoding switch and 20 real keystrokes (`page.keyboard.type`): 22 samples per run, 176 in total,
none discarded. A sample runs from the `input` or `change` event until the IDs, chip IDs, chip
text, token count and character count are all correct, then forced layout.

- CPU: Intel(R) Core(TM) Ultra 9 285K
- OS: Linux 6.18.33.2-microsoft-standard-WSL2 (WSL2)
- Browser: Playwright Chromium 153.0.8010.12

| Corpus | First encoding → switched encoding | n (samples) | Median (ms) | Max (ms) |
| --- | --- | --- | --- | --- |
| prose | r50k_base → o200k_base | 22 | 9.2 | 18.0 |
| prose | o200k_base → r50k_base | 22 | 11.5 | 12.9 |
| code | r50k_base → o200k_base | 22 | 10.7 | 12.6 |
| code | o200k_base → r50k_base | 22 | 12.4 | 15.3 |
| numbers | r50k_base → o200k_base | 22 | 10.3 | 12.1 |
| numbers | o200k_base → r50k_base | 22 | 10.5 | 11.5 |
| unbroken | r50k_base → o200k_base | 22 | 2.0 | 9.4 |
| unbroken | o200k_base → r50k_base | 22 | 9.2 | 10.1 |

All 176 samples are under 50 ms; the largest is 18.0 ms (the first input of the prose run that
starts in r50k_base). Every update rebuilds both strips in full from the current text; nothing from
the previous render is reused. These are host timings, not a slower student laptop.
