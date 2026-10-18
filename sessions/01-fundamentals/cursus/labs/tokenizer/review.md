# Tokenizer lab: review evidence

Agent review by the implementer, 2026-10-13, of the static page built for the edited issue #28
(no real tokenizer: hand-written illustrative examples, a predict-and-reveal and a dated note).
The page has no vendored library, no `script[src]` and no page-specific script; the only script is
the shared runtime block identified by `cursus-script-sha256`.

| File | Bytes | sha256 |
| --- | --- | --- |
| `../tokenizer.html` | 42636 | `0aa2c50112a89d7e280b25a20a90335e3204802df9140ab4977f5dc6a14ea2c2` |

Any edit to the page invalidates this review: re-run the check, look at the screenshots again,
then update the hash, the byte count and the quotes below.

## Check

`node tools/html-pages/check-page.mjs sessions/01-fundamentals/cursus/labs/tokenizer.html --output artifacts/html-pages/tokenizer`
from the repository root, 2026-10-13: PASS, 0 failed checks. Re-run 2026-10-18 on the hash above,
after the fact-check pass (#50) changed only the note's as-of date and added that the old tokenizer
repository is archived: PASS, 0 failed checks; the note was looked at again on screen. The locked suite
`tools/html-pages/tests/tokenizer.test.mjs` writes `tokenizer-no-js.png`, `tokenizer-print.png`,
`tokenizer-reduced-motion.png` and `tokenizer-predict-revealed.png` into the same directory.
Leftover screenshots from the earlier live-tokenizer attempts were deleted from that directory
before this review.

## Screenshots

- **Desktop (1440×900):** masthead, then "What the model actually receives" (three short paragraphs), the predict card with two four-choice questions and Lock in / Reveal / Reset, the amber-ruled illustrative qualification, the ␣ explanation, three example panels and the amber note. Chips sit on one row per example, bordered, alternating teal / amber / red tints, piece on top in monospace and the ID below in smaller monospace; all are legible.
- **Laptop (1280×720):** same order as desktop; both question legends fit on one line, prose stays at about 72 characters per line, and the six number chips fit on one row.
- **Mobile (390×844):** one column with no horizontal overflow; the legends wrap onto two or three lines, the number example wraps its sixth chip ("678 / 15096") onto a second row inside its panel, and the "The model receives" ID list wraps instead of overflowing.
- **No-JS:** both predict answers are visible under their questions, the three buttons are rendered disabled, and the examples and note are identical to the JS view.
- **Print:** light palette; the predict buttons are hidden and both answers printed; chips keep their borders with pale tints, so they stay distinguishable in greyscale; the note keeps its rule and its link text.
- **Reduced motion:** pixel-identical to the desktop capture (`cmp` reports no difference), as the page has no animation or transition of its own.
- **Predict revealed:** after locking both correct choices by keyboard, each question shows "Correct." with its explanation in an accent-ruled block, the status reads "Revealed: 2 of 2 correct." and focus sits on Reset with a visible focus ring.

During this review the first capture showed every chip after the first sitting 8 px lower (a shared
margin on list items); the page now resets the chip margin and the chips align.

## Content review

Explanation (`[data-tok-explain]`), verbatim:

> Before a model reads anything, a tokenizer splits the text into pieces called tokens. A token can be a whole word, part of a word, a few digits or a single character, often with the space in front of it attached. Each token is looked up in a fixed vocabulary and replaced by its integer ID, so a sentence becomes a list of numbers. The model only ever sees that list of IDs, never the letters. Whatever it knows about how a token is spelled, it had to pick up indirectly from training text.

Judgement: accurate and short. It states the three points the issue asks for (text is split into
tokens, each token is an integer ID, the model only sees the IDs) without naming any particular
tokenizer.

Revealed answer to question 1 (token count of " strawberry"), verbatim:

> Two tokens in this illustration: “ straw” with ID 14812 and “berry” with ID 6052. The leading space travels with the first piece. A real tokenizer may cut the word into one, two or more pieces, depending on its vocabulary and on that leading space.

Judgement: matches the two strawberry chips on the page and is scoped to the illustration. It makes
no claim about any specific real tokenizer.

Revealed answer to question 2 (r's the model can see), verbatim:

> A reader sees three r’s in s-t-r-a-w-b-e-r-r-y. The model receives two integer IDs, 14812 and 6052, and no characters at all. It can only pick up spelling facts associated with those IDs from training text, so counting letters is unreliable rather than impossible. The dependable move is to have the model write code that counts them.

Judgement: accurate. It does not claim models can never count letters, only that the letters are
not in the input. It ends with the move the session pivots to: have the model write code.

Note (`[data-tok-note]`), verbatim:

> Every model family has its own tokenizer Each model family uses its own tokenizer, sometimes inherited from an earlier model and sometimes replaced between versions, so the same text splits into different tokens and IDs in GPT-2, GPT-4o, Llama or Claude. The tokenizer used by current Claude models is not public (as of 2026-10-18). Anthropic’s token counting endpoint returns a count of tokens, not the pieces or their IDs, and its documentation notes that Claude Opus 4.7 and later models use a newer tokenizer. Anthropic’s older published tokenizer, anthropic-tokenizer-typescript, archived on 2026-09-01, says it is no longer accurate from the Claude 3 models onward.

Judgement: each claim was checked against a live source on 2026-10-13 and again on 2026-10-18.

- <https://platform.claude.com/docs/en/build-with-claude/token-counting> (the old
  docs.anthropic.com URL redirects here) describes an endpoint whose response "contains the total
  number of input tokens". It also says "Claude 4.7 and later models … use a newer tokenizer",
  which supports both "returns a count" and "replaced between versions".
- <https://github.com/anthropics/anthropic-tokenizer-typescript> says: "As of the Claude 3
  models, this algorithm is no longer accurate".

The note does not deny that an older Anthropic tokenizer was published, and "sometimes inherited"
avoids claiming that no two families ever share a tokenizer.
