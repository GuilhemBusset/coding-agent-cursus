# Tiny real language model lab

[`../tiny-lm.html`](../tiny-lm.html) runs Karpathy's stories260K model (Llama 2 architecture,
about 260,000 parameters, trained only on TinyStories) in the page. Each Step is one forward pass,
one seeded random draw and one appended token. Open the file directly in a browser; it needs no
server and no network.

## What is in the page

- `script#tiny-lm-weights`: `stories260K/stories260K.bin` (1,056,540 bytes), base64, 120 columns.
- `script#tiny-lm-tokenizer`: `stories260K/tok512.bin` (6,227 bytes), base64, 120 columns.
- A JavaScript port of llama2.c `run.c` (forward pass, `encode`, `decode`) and the sampler,
  in classic inline script on the main thread: no WebAssembly, worker, module or network request.

Page weight: about 1.5 MB (1,500,681 bytes when this README was written), almost all of it
the base64 weights. Each data block's `data-sha256` is the sha256 of its decoded bytes.

## Files here

| File | Purpose |
| --- | --- |
| `provenance.json` | Pinned Hugging Face revision and llama2.c commit, URLs, byte lengths, sha256 and licences. |
| `embed_weights.py` | Re-embeds both files into the page (standard library only). |
| `reference/run.c`, `reference/LICENSE` | llama2.c at the pinned commit, unchanged. |
| `reference/logits_driver.c` | Test oracle: compiles `run.c` with `TESTING` defined and prints per-position logits. |
| `review.md` | Review evidence: screenshots, caption, attribution, timings. |

## Regenerate the embedded data

```sh
python3 sessions/01-fundamentals/cursus/labs/tiny-lm/embed_weights.py
```

It downloads both files from the immutable `resolve/<revision>/` URLs in `provenance.json`,
refuses anything whose length or sha256 differs, and rewrites only the two data blocks. With
`--source-dir DIR` it reads `stories260K.bin` and `tok512.bin` from `DIR` instead, with the same
checks. To move to another revision, update `provenance.json` first (revision, URLs, lengths,
hashes), re-run the script, then re-run the test below and re-review the page (`review.md`
records the page's sha256).

## Test

```sh
node tools/html-pages/tests/run-suite.mjs tools/html-pages/tests/tiny-lm.test.mjs
```

The suite decodes the weights and tokenizer from the page itself and compiles
`reference/logits_driver.c` with the system C compiler (`cc -O2 -std=gnu11 -ffp-contract=off -lm`;
a C compiler such as gcc or clang must be installed, see `setup/README.md`). Then it checks that the page's token ids
equal llama2.c's and that every logit at every position is within 1e-4 on three prompts. It
also covers stepping, rewind, sampling, reproducibility, the caption, attribution, offline loading
and first-token timing. A missing compiler fails the suite; nothing is skipped.

## Licences

- Weights and tokenizer: [karpathy/tinyllamas](https://huggingface.co/karpathy/tinyllamas) by
  Andrej Karpathy, MIT according to the model card's `license` field at the pinned revision.
- Code: the page's forward pass, `encode` and `decode` are ported from
  [karpathy/llama2.c](https://github.com/karpathy/llama2.c) `run.c` (MIT, `reference/LICENSE`,
  which reads "Copyright (c) 2023 Andrej"). The page shows that notice in full in its footer.
