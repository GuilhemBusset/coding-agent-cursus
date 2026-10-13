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

## How the page turns IDs into chip text

The page never calls the library's `decode()` for chips. In 3.4.0, `decode()` and the decode
generators share one module-level `TextDecoder` and call it with `{stream: true}` without ever
flushing it. A token that holds only the first bytes of a character (🍓 is two o200k_base tokens,
`[240, 159, 141]` then `[147]`) leaves those bytes pending, and the next decode anywhere on the page
starts with them. After one stray `decode([102415])`, decoding the IDs of "🍓🍓" token by token gives
`"�"` for the first piece instead of `""`. Chip text would then depend on what was decoded before.

The page uses the first byte source the design allows: the rank table, which the exported encoding
object exposes at runtime. For each ID it calls
`GPTTokenizer_<encoding>.bytePairEncodingCoreProcessor.tryDecodeToken(id)`, a read-only lookup
that returns the token's text (a string) or its raw bytes (a `Uint8Array`) when the token is not
whole UTF-8. A string token that starts a chip is the chip text as it is. Byte tokens are grouped:
the page joins the shortest run of consecutive tokens whose bytes end on a whole UTF-8 character
and decodes that group with a fresh, non-streaming `new TextDecoder('utf-8', { ignoreBOM: true })`.
So one character split across tokens gets one chip carrying all its IDs (`data-token-ids`), with a
×2 or ×3 badge; 🍓 in o200k_base is one chip with IDs `102415 241`, and hovering it highlights both
IDs. Every chip's text depends only on its own IDs, never on an earlier decode, and each render
rebuilds both strips from the current text and encoding. `ignoreBOM` matters: without it the
decoder drops a leading U+FEFF as a byte-order mark, and the chips for `"\uFEFFb"` would join to
`"b"` while still counting U+FEFF's IDs. The ID strip keeps one span per token (`data-index` is the
token index, `data-chip-index` its chip), so no token boundary is hidden.
The vendored files are not edited. The reset-wrapped `decode()` fallback is not needed.

Do not switch to another version or an ESM build. If the files change, update
`provenance.json`, the page weight below, the page's `[data-tok-weight]` line, and the hashes and
static numbers on the page (the comparison table and the predict answers come from these
encoders). Then re-run the review in `review.md`.

## Page weight

Raw bytes on disk, without compression; 1 MB = 1,000,000 bytes. The browser reads all three files
when the page opens.

| File | Bytes | MB |
| --- | --- | --- |
| `tokenizer.html` | 60,271 | 0.060 |
| `vendor/r50k_base.js` | 502,907 | 0.503 |
| `vendor/o200k_base.js` | 2,047,463 | 2.047 |
| o200k-only subtotal (`tokenizer.html` + `o200k_base.js`) | 2,107,734 | 2.108 |
| Full total (all three files) | 2,610,641 | 2.611 (2.490 MiB) |

The issue estimated "about 2.5 MB with o200k". Measured, the o200k-only subtotal is 2.108 MB and the whole page, with GPT-2's encoder as well, is 2.611 MB (2.490 MiB). The page footer shows the total rounded to one decimal. Neither encoder is trimmed to reach a target.
