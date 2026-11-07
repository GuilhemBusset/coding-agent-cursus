import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../../../../tools/html-pages/browser.mjs';
import { repoRoot, count, textOf } from '../../../../tools/html-pages/tests/component-helpers.mjs';

/* The tokenizer lab is static markup: three worked examples written into the page as chips (piece
 * and ID), and a predict card. The examples must be GPT-2's real tokenizations, and the card's key
 * must agree with them and with the deck's fixture. Layout, axe, no-JS, print and reduced motion
 * are check-page.mjs's job; the predict component itself is predict.test.mjs's. */
const file = path.join(repoRoot, 'sessions/01-fundamentals/cursus/labs/tokenizer.html');
const fixture = path.join(repoRoot, 'sessions/01-fundamentals/cursus/fixtures/next_token.json');
// openai-community/gpt2 at the fixtures' pinned revision; tiktoken's gpt2 encoding gives the same
// pieces and IDs.
const GPT2 = {
  blueberry: { source: ' blueberry', pieces: [' blue', 'berry'], ids: [4171, 8396] },
  bonjour: { source: 'Bonjour', pieces: ['Bon', 'j', 'our'], ids: [20682, 73, 454] },
  number: {
    source: '123456789012345678',
    pieces: ['123', '45', '67', '89', '01', '23', '45', '678'],
    ids: [10163, 2231, 3134, 4531, 486, 1954, 2231, 30924],
  },
};
const normal = text => text.replace(/\s+/g, ' ').trim();
const labelOf = radio => radio.evaluate(el => [...el.labels].map(label => label.textContent.trim()).join(' '));

// One browser for the file, a fresh context per test.
let browser;
after(() => browser?.close());
async function pageFor(t) {
  browser ??= await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  t.after(async () => { await context.close(); assert.deepEqual(errors, [], 'no runtime errors or remote requests'); });
  await context.route(/^(https?|wss?):/i, route => { errors.push(`remote request: ${route.request().url()}`); return route.abort(); });
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(pathToFileURL(file).href);
  return page;
}

function visibleInteger(text) {
  // A label such as "ID 17" is fine; attributes alone are not an ID readout.
  const match = normal(text).match(/^(?:(?:token\s+)?ID\s*[:#]?\s*)?(\d+)$/i);
  assert.ok(match, `one visible non-negative integer ID, got ${JSON.stringify(text)}`);
  return Number(match[1]);
}

// What each chip shows: its rendered piece (CSS space marks included, the ID excluded) and its ID.
async function renderedExamples(page) {
  return page.locator('figure[data-tok-example]').evaluateAll(figures => figures.map(figure => {
    function generated(node, pseudo) {
      const css = getComputedStyle(node, pseudo), content = css.content;
      if (css.display === 'none' || css.visibility === 'hidden' || Number(css.opacity) === 0 || parseFloat(css.fontSize) === 0) return '';
      if (!/^['"]/.test(content)) return '';
      return content.slice(1, -1).replace(/\\([0-9a-f]{1,6})\s?|\\(.)/gi,
        (_, hex, literal) => hex ? String.fromCodePoint(parseInt(hex, 16)) : literal);
    }
    function read(node) {
      if (node.nodeType === Node.TEXT_NODE) return parseFloat(getComputedStyle(node.parentElement).fontSize) === 0 ? '' : node.textContent;
      if (node.nodeType !== Node.ELEMENT_NODE || node.matches('[data-tok-id]')) return '';
      const css = getComputedStyle(node);
      if (node.hidden || css.display === 'none' || ['hidden', 'collapse'].includes(css.visibility) || Number(css.opacity) === 0 ||
          (css.clip !== 'auto' && node.getBoundingClientRect().width <= 1)) return '';
      const before = generated(node, '::before'), after = generated(node, '::after');
      let contents = [...node.childNodes].map(read).join('');
      // A pseudo-element marking a whitespace-only span represents that space; do not count it twice.
      if (/^\s+$/.test(contents) && (before || after)) contents = '';
      return before + contents + after;
    }
    return { key: figure.dataset.tokExample, source: figure.querySelector('[data-tok-text]')?.textContent,
      chips: [...figure.querySelectorAll('ol > li[data-tok-chip]')].map(chip => ({
        visible: chip.checkVisibility(), piece: read(chip).trim(), id: chip.querySelector('[data-tok-id]')?.innerText ?? '' })) };
  }));
}

test("the worked examples are GPT-2's real pieces and IDs, and the pieces rebuild the source", async t => {
  const page = await pageFor(t);
  const figures = await renderedExamples(page);
  assert.deepEqual(figures.map(f => f.key).sort(), Object.keys(GPT2).sort(), 'three named worked examples');
  const blueberry = figures.find(f => f.key === 'blueberry');
  // The leading space is shown as a visible marker; no particular glyph is prescribed.
  const marker = [...blueberry.chips[0].piece][0];
  assert.match(marker, /[^\p{L}\p{N}\s]/u, 'leading space is a visible marker');
  const vocabulary = new Map();
  for (const { key, source, chips } of figures) {
    const pieces = [], ids = [];
    for (const chip of chips) {
      assert.ok(chip.visible && chip.piece, `${key}: each chip shows its piece`);
      const piece = chip.piece.split(marker).join(' '), id = visibleInteger(chip.id);
      if (vocabulary.has(piece)) assert.equal(id, vocabulary.get(piece), `repeated piece ${JSON.stringify(piece)} keeps its ID`);
      vocabulary.set(piece, id);
      pieces.push(piece); ids.push(id);
    }
    assert.equal(pieces.join(''), source, `${key}: rendered pieces rebuild the exact source`);
    assert.deepEqual({ source, pieces, ids }, GPT2[key], `${key}: GPT-2's real pieces and IDs`);
  }
});

test("the predict card's key matches the chips and the deck's fixture, and the card locks, reveals and resets", async t => {
  const page = await pageFor(t);
  const root = page.locator('[data-predict]');
  await count(root, 1);
  const questions = root.locator('fieldset[data-predict-question]');
  await count(questions, 2);
  const [q1, q2] = [questions.nth(0), questions.nth(1)];
  // Question 1: how many tokens is " blueberry"? The key and the revealed answer give the chip count.
  const n = await page.locator('figure[data-tok-example="blueberry"] [data-tok-chip]').count();
  const words = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];
  const counts = [...normal(await labelOf(q1.locator('input[data-correct]'))).matchAll(new RegExp(`\\b(?:\\d+|${words.join('|')})\\b`, 'gi'))]
    .map(match => /^\d+$/.test(match[0]) ? Number(match[0]) : words.indexOf(match[0].toLowerCase()));
  assert.deepEqual(counts, [n], 'the correct token-count choice equals the displayed chip count');
  const answer1 = normal(await q1.locator('[data-predict-answer]').textContent());
  assert.match(answer1, new RegExp(`\\b(?:${n}|${words[n]})\\b`, 'i'), 'the revealed answer gives the same count');
  const strawberry = JSON.parse(await readFile(fixture, 'utf8')).prompts.find(item => item.prompt === ' strawberry');
  assert.equal(strawberry?.prompt_tokens.length, 1, 'the fixture keeps the leading-space strawberry whole');
  assert.match(answer1, new RegExp(`\\b${strawberry.prompt_tokens[0].id}\\b`), "the strawberry contrast uses the deck's fixture ID");
  // Question 2: how many letters does the model see? None: only the IDs the chips show.
  assert.match(await labelOf(q2.locator('input[data-correct]')), /\b(?:none|zero|0)\b/i);
  const answer2 = normal(await q2.locator('[data-predict-answer]').textContent());
  for (const id of GPT2.blueberry.ids) assert.match(answer2, new RegExp(`\\b${id}\\b`), 'the answer names the IDs shown in the chips');
  for (const question of [q1, q2]) await question.locator('input[data-correct]').check();
  await root.locator('[data-predict-lock]').click();
  await root.locator('[data-predict-reveal]').click();
  for (const question of [q1, q2]) {
    assert.equal(await textOf(question.locator('[data-predict-result]')), 'Correct.');
    assert.equal(await question.locator('[data-predict-answer]').isVisible(), true);
  }
  await root.locator('[data-predict-reset]').click();
  await count(root.locator('input:checked'), 0);
  assert.equal(await q1.locator('[data-predict-answer]').isVisible(), false, 'Reset hides the answers again');
});
