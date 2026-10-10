# Tokenizer lab: vendored encoders

`../tokenizer.html` tokenizes typed text in the browser with two encoders from
[gpt-tokenizer](https://www.npmjs.com/package/gpt-tokenizer/v/3.4.0) 3.4.0 (MIT, Bazyli Brzoska):

| Vendored file | Encoding | Global it defines | Source in the npm tarball |
| --- | --- | --- | --- |
| `vendor/r50k_base.js` | GPT-2's r50k_base | `GPTTokenizer_r50k_base` | `package/dist/r50k_base.js` |
| `vendor/o200k_base.js` | OpenAI's o200k_base (GPT-4o family) | `GPTTokenizer_o200k_base` | `package/dist/o200k_base.js` |
| `vendor/LICENSE` | MIT licence text | — | `package/LICENSE` |

The page loads both as classic `<script src>` files, so it works from `file://` with no server,
module loader or network access. They are byte-for-byte copies of the release files; nothing is
minified, patched or inlined. Each ends with a `//# sourceMappingURL` comment, but the `.map` files
are deliberately not vendored. Browsers only request a map when developer tools are open, and a
missing map changes nothing on the page.

Why 3.4.0: it is the last release that ships the UMD builds in `dist/`. Version 4 (4.0.0,
published 2026-08-16) dropped the UMD build and ships only `cjs/` and `esm/` modules, which a
page opened from `file://` cannot load as classic scripts.

`provenance.json` records the tarball URL, its npm `integrity`, the retrieval date (2026-10-10),
and each file's source path, byte count and sha256. `review.md` holds the `npm pack` transcript
and the review of the page.

## Refresh or verify

From a new, empty temporary directory (lifecycle scripts off):

```sh
npm pack gpt-tokenizer@3.4.0 --ignore-scripts --json   # the "integrity" field must match provenance.json
tar -xzf gpt-tokenizer-3.4.0.tgz
sha256sum package/dist/r50k_base.js package/dist/o200k_base.js package/LICENSE
cp package/dist/r50k_base.js package/dist/o200k_base.js package/LICENSE <repo>/sessions/01-fundamentals/cursus/labs/tokenizer/vendor/
```

Do not switch to another version or an ESM build. If the files change, update
`provenance.json`, the page weight below, the page's `[data-tok-weight]` line, and the hashes and
static numbers on the page (the comparison table and the predict answers come from these
encoders). Then re-run the review in `review.md`. `setup/README.md` has the same recipe.

## Page weight

Raw bytes on disk, without compression; 1 MB = 1,000,000 bytes. The browser reads all three files
when the page opens.

| File | Bytes | MB |
| --- | --- | --- |
| `tokenizer.html` | 57,179 | 0.057 |
| `vendor/r50k_base.js` | 502,907 | 0.503 |
| `vendor/o200k_base.js` | 2,047,463 | 2.047 |
| o200k-only subtotal (`tokenizer.html` + `o200k_base.js`) | 2,104,642 | 2.105 |
| Full total (all three files) | 2,607,549 | 2.608 |

The issue estimated "about 2.5 MB with o200k". Measured, the o200k-only subtotal is 2.105 MB and the whole page, with GPT-2's encoder as well, is 2.608 MB. The page footer shows the total rounded to one decimal. Neither encoder is trimmed to reach a target.
