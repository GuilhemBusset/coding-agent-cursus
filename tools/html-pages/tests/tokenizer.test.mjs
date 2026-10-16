import test from 'node:test';
import assert from 'node:assert/strict';
import { access, copyFile, mkdir, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import vm from 'node:vm';
import { chromium } from '../browser.mjs';
import {
  repoRoot, suites, scratch, openPage, count, enabled, focused, initialPredict, textOf, escapeRegExp,
} from './component-helpers.mjs';

// Issue 28, amended 2026-10-13: static, hand-written illustrations, no tokenizer.
// Public markup is the oracle; no private functions, real encoding, or chosen IDs
// are prescribed. D1/D4 accuracy and visual composition are agent-review items,
// not facts that keyword matching or a self-authored review can establish.
const relative = 'sessions/01-fundamentals/cursus/labs/tokenizer.html';
const file = path.join(repoRoot, relative);
const evidence = path.join(repoRoot, 'sessions/01-fundamentals/cursus/labs/tokenizer/review.md');
const output = path.join(repoRoot, 'artifacts/html-pages/tokenizer');
const checkCommand = `node tools/html-pages/check-page.mjs ${relative} --output artifacts/html-pages/tokenizer`;
const normal = text => text.replace(/\s+/g, ' ').trim();
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const pageFor = (t, options = {}) => openPage(t, chromium, { file, offline: true, ...options });
const labelOf = radio => radio.evaluate(el => [...el.labels].map(label => label.textContent.trim()).join(' '));

async function screenshot(page, name) {
  await mkdir(output, { recursive: true });
  await page.screenshot({ path: path.join(output, `tokenizer-${name}.png`), fullPage: true });
}

async function visibleNonempty(locator) {
  await count(locator, 1);
  assert.equal(await locator.isVisible(), true);
  assert.ok(normal(await locator.innerText()), 'content must be readable, not only an attribute');
}

async function structure(page) {
  assert.equal(await page.locator('html').getAttribute('data-design-system'), 'cursus');
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'lab');
  await visibleNonempty(page.locator('[data-tok-explain]'));
  await count(page.locator('[data-predict]'), 1);
  await count(page.locator('figure[data-tok-example]'), 3);
  await visibleNonempty(page.locator('aside[data-tok-note]'));
  assert.equal(await page.evaluate(() => {
    const nodes = [document.querySelector('[data-tok-explain]'), document.querySelector('[data-predict]'),
      ...document.querySelectorAll('figure[data-tok-example]'), document.querySelector('[data-tok-note]')];
    return nodes.every((node, i) => !i || !!(nodes[i - 1].compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING));
  }), true, 'explanation, predict card, examples, note appear in teaching order');
  const reserved = await page.locator('*').evaluateAll(nodes => nodes.flatMap(el => [...el.attributes]
    .filter(a => /^data-(?:lab$|reset$|budget)/.test(a.name)).map(a => a.name)));
  assert.deepEqual(reserved, [], 'remove the starter budget interaction');
}

function visibleInteger(text) {
  // A label such as "ID 17" is fine; attributes alone are not an ID readout.
  const match = normal(text).match(/^(?:(?:token\s+)?ID\s*[:#]?\s*)?(\d+)$/i);
  assert.ok(match, `one visible non-negative integer ID, got ${JSON.stringify(text)}`);
  const value = Number(match[1]);
  assert.ok(Number.isSafeInteger(value), 'IDs are representable integers');
  return value;
}

async function chipPiece(chip) {
  // Read rendered text, excluding the separately identified ID. Include CSS
  // space marks as well as authored glyphs; neither data-text nor an accessible
  // name substitutes for the visible piece.
  return chip.evaluate(el => {
    function generated(node, pseudo) {
      const css = getComputedStyle(node, pseudo), content = css.content;
      if (css.display === 'none' || css.visibility === 'hidden' || Number(css.opacity) === 0 || parseFloat(css.fontSize) === 0) return '';
      if (!/^['"]/.test(content)) return '';
      return content.slice(1, -1).replace(/\\([0-9a-f]{1,6})\s?|\\(.)/gi,
        (_, hex, literal) => hex ? String.fromCodePoint(parseInt(hex, 16)) : literal);
    }
    function read(node) {
      if (node.nodeType === Node.TEXT_NODE) {
        return parseFloat(getComputedStyle(node.parentElement).fontSize) === 0 ? '' : node.textContent;
      }
      if (node.nodeType !== Node.ELEMENT_NODE || node.matches('[data-tok-id]')) return '';
      const css = getComputedStyle(node);
      if (node.hidden || css.display === 'none' || ['hidden', 'collapse'].includes(css.visibility) || Number(css.opacity) === 0 ||
          (css.clip !== 'auto' && node.getBoundingClientRect().width <= 1)) return '';
      const before = generated(node, '::before'), after = generated(node, '::after');
      let contents = [...node.childNodes].map(read).join('');
      // A pseudo-element marking a whitespace-only span represents that space;
      // the span's raw blank must not be counted a second time.
      if (/^\s+$/.test(contents) && (before || after)) contents = '';
      return before + contents + after;
    }
    return read(el).trim();
  });
}

const transparent = color => color === 'transparent' || /rgba\([^)]*,\s*0(?:\.0+)?\s*\)/.test(color);
async function examples(page) {
  const figures = page.locator('figure[data-tok-example]');
  await count(figures, 3);
  const byKey = {}, vocabulary = new Map();
  for (const figure of await figures.all()) {
    const key = await figure.getAttribute('data-tok-example');
    assert.ok(['strawberry', 'bonjour', 'number'].includes(key), 'three named worked examples');
    assert.ok(!byKey[key], 'example keys are unique');
    await visibleNonempty(figure.locator('[data-tok-text]'));
    const source = await figure.locator('[data-tok-text]').textContent();
    if (key === 'strawberry') assert.equal(source, ' strawberry', 'preserve the leading space');
    if (key === 'bonjour') assert.equal(source, 'Bonjour');
    if (key === 'number') assert.match(source, /^\d{10,}$/, 'a long number');
    await count(figure.locator('ol'), 1);
    const chips = figure.locator('ol > li[data-tok-chip]');
    assert.ok(await chips.count() >= 2, 'show the split as several ordered chips');
    await count(figure.locator('[data-tok-chip]'), await chips.count());
    const pieces = [], ids = [];
    let previousBackground;
    for (const chip of await chips.all()) {
      assert.equal(await chip.isVisible(), true);
      await visibleNonempty(chip.locator('[data-tok-id]'));
      const id = visibleInteger(await chip.locator('[data-tok-id]').innerText());
      let piece = await chipPiece(chip);
      assert.ok(piece, 'chip has visible piece text in addition to its ID');
      if (key === 'strawberry' && !pieces.length) {
        const marker = [...piece][0];
        assert.match(marker, /[^\p{L}\p{N}\s]/u, 'leading space is a visible marker');
        // The convention must be explained outside the examples, not only in a
        // chip's accessible name. No particular marker glyph is prescribed.
        const explanations = await page.locator('body *').evaluateAll(nodes => nodes.filter(el => {
          const css = getComputedStyle(el);
          return !el.closest('figure[data-tok-example]') && !el.querySelector('figure[data-tok-example]') &&
            el.getClientRects().length && css.display !== 'none' && css.visibility !== 'hidden' && Number(css.opacity) > 0;
        }).map(el => el.innerText || ''));
        assert.ok(explanations.some(text => text.includes(marker) && /(?:white\s*space|space|blank)/i.test(text)),
          'explain the visible space marker once on the page');
        byKey.marker = marker;
      }
      if (byKey.marker) piece = piece.split(byKey.marker).join(' ');
      const aria = await chip.getAttribute('aria-label');
      assert.ok(aria, 'each chip names its piece and ID accessibly');
      assert.match(aria, new RegExp(`^piece\\s+["“]${escapeRegExp(piece)}["”],\\s*ID\\s+${id}\\s*$`, 'i'));
      if (vocabulary.has(piece)) assert.equal(id, vocabulary.get(piece), `repeated piece ${JSON.stringify(piece)} keeps its ID`);
      vocabulary.set(piece, id);
      pieces.push(piece); ids.push(id);
      const css = await chip.evaluate(el => {
        const style = getComputedStyle(el);
        return { background: style.backgroundColor, borders: ['Top', 'Right', 'Bottom', 'Left'].map(side =>
          ({ width: parseFloat(style[`border${side}Width`]), style: style[`border${side}Style`], color: style[`border${side}Color`] })) };
      });
      assert.ok(!transparent(css.background), 'every chip is tinted');
      assert.notEqual(css.background, previousBackground, 'neighbouring chips have different tints');
      previousBackground = css.background;
      assert.ok(css.borders.every(border => border.width > 0 && !['none', 'hidden'].includes(border.style) && !transparent(border.color)),
        'each chip has a visible border in addition to colour');
    }
    assert.equal(pieces.join(''), source, `${key}: rendered pieces reconstruct the exact source`);
    byKey[key] = { source, pieces, ids };
  }
  // Require a shared, visible qualification before all the worked examples.
  // This is a narrow labelling guard; accuracy of the prose is still reviewed.
  const qualified = await page.locator('body *').evaluateAll(nodes => nodes.some(el => {
    const text = el.innerText || '';
    const first = document.querySelector('figure[data-tok-example]');
    const style = getComputedStyle(el);
    return /illustrative/i.test(text) && /splits?/i.test(text) && /\bIDs?\b/i.test(text) &&
      /(?:written\s+by\s+hand|hand[- ]written)/i.test(text) &&
      !el.closest('figure[data-tok-example]') && !el.contains(first) && style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) > 0 &&
      el.getClientRects().length > 0 && !!(el.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING);
  }));
  assert.equal(qualified, true, 'one visible hand-written illustrative qualification covers all examples');
  return byKey;
}

async function predictContract(page) {
  const root = page.locator('[data-predict]');
  await count(root, 1);
  const questions = root.locator('fieldset[data-predict-question]');
  await count(questions, 2);
  for (const name of ['lock', 'reveal', 'reset']) await count(root.locator(`button[data-predict-${name}]`), 1);
  await count(root.locator('[data-predict-status][role=status]'), 1);
  for (const question of await questions.all()) {
    await visibleNonempty(question.locator('legend'));
    const radios = question.locator('input[type=radio]');
    assert.ok(await radios.count() >= 2, 'a prediction offers a choice');
    await count(question.locator('input[type=radio][data-correct]'), 1);
    const names = await radios.evaluateAll(nodes => nodes.map(el => el.name));
    assert.ok(names[0] && names.every(name => name === names[0]), 'each question is a native radio group');
    for (const radio of await radios.all()) assert.ok(normal(await labelOf(radio)), 'all choices have native labels');
    await count(question.locator('[data-predict-result]'), 1);
    await count(question.locator('[data-predict-answer]'), 1);
    assert.ok(normal(await question.locator('[data-predict-answer]').textContent()).length > 20, 'authored explanations');
  }
  assert.notEqual(await questions.nth(0).locator('input').first().getAttribute('name'),
    await questions.nth(1).locator('input').first().getAttribute('name'), 'questions are independent radio groups');
  const q1 = questions.nth(0), q2 = questions.nth(1);
  const legend1 = await textOf(q1.locator('legend')), legend2 = await textOf(q2.locator('legend'));
  assert.match(legend1, /strawberry/i);
  assert.match(legend1, /tokens?/i);
  assert.match(legend1, /how\s+many|(?:number|count)\s+of|token\s+count/i);
  assert.match(legend1, /illustrative/i, 'prediction is scoped to the fictional illustration');
  assert.match(legend1, /(?:leading|initial)\s+(?:space|blank)|["'“‘] strawberry|[␣␠]strawberry/i,
    'question preserves or explicitly mentions the leading space');
  assert.match(legend2, /\br(?:['’]s|s)?\b/i);
  assert.match(legend2, /model/i);
  assert.match(legend2, /see/i);
  assert.match(legend2, /how\s+many|number|count/i);
  const n = await page.locator('figure[data-tok-example="strawberry"] [data-tok-chip]').count();
  const label1 = normal(await labelOf(q1.locator('input[data-correct]')));
  const words = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];
  const counts = [...label1.matchAll(new RegExp(`\\b(?:\\d+|${words.join('|')})\\b`, 'gi'))]
    .map(match => /^\d+$/.test(match[0]) ? Number(match[0]) : words.indexOf(match[0].toLowerCase()));
  assert.deepEqual(counts, [n], 'correct token-count choice equals the displayed chip count');
  assert.match(normal(await q1.locator('[data-predict-answer]').textContent()),
    new RegExp(`\\b(?:${n}${words[n] ? `|${words[n]}` : ''})\\b`, 'i'), 'revealed token-count answer accompanies the correct choice');
  assert.match(await labelOf(q2.locator('input[data-correct]')), /\b(?:none|zero|0)\b/i);
  const explanation = normal(await q2.locator('[data-predict-answer]').textContent());
  assert.match(explanation, /\b(?:integer\s+IDs?|IDs?)\b/i);
  assert.match(explanation, /\b(?:3|three)\b.{0,80}\br(?:['’]s|s)?\b/i, 'distinguish the three letters a reader sees from IDs');
  return { root, questions };
}

async function cycle(page, choices, keyboard = false) {
  const { root, questions } = await predictContract(page);
  await initialPredict(root);
  // Choose in reverse order on alternating runs. A hard-coded score or a
  // handler that only watches question 1 cannot satisfy the mixed cases.
  const order = choices[0] ? [0, 1] : [1, 0];
  for (const [step, index] of order.entries()) {
    const selector = choices[index] ? 'input[type=radio][data-correct]' : 'input[type=radio]:not([data-correct])';
    const radio = questions.nth(index).locator(selector).first();
    if (keyboard) { await radio.focus(); await radio.press('Space'); }
    else await radio.check();
    await enabled(root.locator('[data-predict-lock]'), step === 1);
    await enabled(root.locator('[data-predict-reveal]'), false);
    for (const answer of await root.locator('[data-predict-answer]').all()) assert.equal(await answer.isVisible(), false);
  }
  const activate = async locator => {
    if (keyboard) { await locator.focus(); await locator.press('Enter'); }
    else await locator.click();
  };
  await activate(root.locator('[data-predict-lock]'));
  await enabled(root.locator('[data-predict-lock]'), false);
  await enabled(root.locator('[data-predict-reveal]'));
  await focused(root.locator('[data-predict-reveal]'));
  for (const radio of await root.locator('input[type=radio]').all()) await enabled(radio, false);
  for (const answer of await root.locator('[data-predict-answer]').all()) assert.equal(await answer.isVisible(), false);
  await activate(root.locator('[data-predict-reveal]'));
  await enabled(root.locator('[data-predict-reveal]'), false);
  await focused(root.locator('[data-predict-reset]'));
  for (let i = 0; i < 2; i++) {
    const question = questions.nth(i), answer = question.locator('[data-predict-answer]');
    assert.equal(await answer.isVisible(), true);
    assert.ok(await answer.ariaSnapshot(), 'revealed answer is available to assistive technology');
    const correct = await labelOf(question.locator('input[data-correct]'));
    assert.equal(await textOf(question.locator('[data-predict-result]')),
      choices[i] ? 'Correct.' : `Not quite. The answer is ${correct}.`);
  }
  const answers = await root.locator('[data-predict-answer]').allTextContents();
  if (choices.every(Boolean) && keyboard) await screenshot(page, 'predict-revealed');
  await activate(root.locator('[data-predict-reset]'));
  await initialPredict(root);
  await focused(root.locator('input[type=radio]').first());
  return answers.map(normal);
}

// Literal-table inspection is structural, not a ban on the words "tokenizer",
// "fetch", etc. in prose, comments, reference URLs or explanatory strings.
// Classic-script compilation also rejects static imports; lexical tokens catch
// dynamic imports without accidentally matching documentation text.
function scriptTokens(source) {
  const re = /(?<comment>\/\/[^\n]*|\/\*[\s\S]*?\*\/)|(?<string>"(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'|`(?:\\[\s\S]|[^`\\])*`)|(?<number>\b\d+(?:\.\d+)?\b)|(?<word>[A-Za-z_$][\w$]*)|(?<punct>[^\s])/g;
  return [...source.matchAll(re)].filter(m => !m.groups.comment).map(m => ({
    kind: Object.entries(m.groups).find(([, value]) => value !== undefined)[0], value: m[0],
  }));
}
function inspectScript(source, executable = true) {
  // Syntax only. Never execute the implementation in Node.
  if (executable) new vm.Script(source);
  else JSON.parse(source);
  const tokens = scriptTokens(source);
  for (let i = 0; i < tokens.length; i++) {
    assert.ok(!(tokens[i].kind === 'word' && tokens[i].value === 'import' && ['(', '.'].includes(tokens[i + 1]?.value)),
      'no dynamic or module import');
  }
  // String-to-integer rank maps and arrays of such pairs are vocabulary/merge
  // tables regardless of their variable names. String-pair arrays are merge
  // tables. Ordinary enhancement code and descriptive strings are allowed.
  const patterns = [
    /(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*:\s*\d+\s*,\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*:\s*\d+/,
    /\[\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*,\s*\d+\s*\]\s*,\s*\[\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*,\s*\d+\s*\]/,
    /\d+\s*:\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*,\s*\d+\s*:\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')/,
    /\[\s*\d+\s*,\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*\]\s*,\s*\[\s*\d+\s*,\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*\]/,
    /\[\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*,\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*\]\s*,\s*\[\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*,\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')\s*\]/,
  ];
  const uncommented = tokens.map(token => token.value).join(' ');
  for (const pattern of patterns) assert.doesNotMatch(uncommented, pattern, 'no inline vocabulary or merge table');
}

async function staticRuntime(page, source) {
  await count(page.locator('script[src]'), 0);
  await count(page.locator('script[type="module"]'), 0);
  await count(page.locator('link[rel="modulepreload"], iframe, object, embed'), 0);
  await count(page.locator('textarea, input:not([type=radio]):not([type=hidden]), [contenteditable]:not([contenteditable=false])'), 0);
  const blocks = [...source.matchAll(/<!-- shared-script:begin -->\s*<script[^>]*>([\s\S]*?)<\/script>\s*<!-- shared-script:end -->/g)];
  assert.equal(blocks.length, 1, 'one identified shared runtime snapshot');
  const meta = page.locator('meta[name="cursus-script-sha256"]');
  await count(meta, 1);
  assert.equal(await meta.getAttribute('content'), hash(blocks[0][1]), 'shared runtime metadata identifies the actual embedded block');
  for (const script of await page.locator('script').all()) {
    const type = (await script.getAttribute('type') || '').toLowerCase();
    const data = ['application/json', 'application/ld+json'].includes(type);
    assert.ok(!type || ['text/javascript', 'application/javascript', 'text/ecmascript', 'application/ecmascript'].includes(type) || data,
      'classic inline scripts or inert JSON metadata; no modules');
    inspectScript(await script.textContent(), !data);
  }
}

test('D1/D2: visible explanation and lossless illustrative chips with IDs, JS and no-JS', { timeout: 60000 }, async t => {
  let baseline;
  for (const javaScriptEnabled of [true, false]) {
    const page = await pageFor(t, { javaScriptEnabled });
    await structure(page);
    const current = await examples(page);
    baseline ??= current;
    assert.deepEqual(current, baseline, 'examples are authored, not generated at runtime');
  }
});

test('D3: pointer and keyboard lock/reveal/reset, all four correctness combinations', { timeout: 60000 }, async t => {
  const page = await pageFor(t);
  await structure(page);
  for (const [i, choices] of [[false, false], [true, false], [false, true], [true, true]].entries()) {
    await cycle(page, choices, i % 2 === 1);
  }
  const { root, questions } = await predictContract(page);
  // Reset is meaningful during a partial prediction and after locking before reveal.
  await questions.nth(1).locator('input[data-correct]').check();
  await root.locator('[data-predict-reset]').click();
  await initialPredict(root);
  for (const question of await questions.all()) await question.locator('input[data-correct]').check();
  await root.locator('[data-predict-lock]').click();
  await root.locator('[data-predict-reset]').click();
  await initialPredict(root);
  await focused(root.locator('input[type=radio]').first());
});

test('D1/D3/D4: authored answers and stable dated note survive no-JS and print', { timeout: 60000 }, async t => {
  const js = await pageFor(t);
  await visibleNonempty(js.locator('[data-tok-explain]'));
  const answers = await cycle(js, [true, true]);
  const explain = normal(await js.locator('[data-tok-explain]').innerText());
  let noteText, noteLinks;
  for (const mode of ['js', 'no-js', 'print']) {
    const page = mode === 'js' ? js : await pageFor(t, { javaScriptEnabled: mode !== 'no-js' });
    if (mode === 'print') {
      await page.emulateMedia({ media: 'print' });
      await page.evaluate(() => window.dispatchEvent(new Event('beforeprint')));
    }
    await visibleNonempty(page.locator('[data-tok-explain]'));
    assert.equal(normal(await page.locator('[data-tok-explain]').innerText()), explain);
    const note = page.locator('aside[data-tok-note]');
    await visibleNonempty(note);
    const current = normal(await note.innerText());
    noteText ??= current;
    assert.equal(current, noteText, 'same static note with JS, without JS and in print');
    assert.match(current, /as[- ]of\s+\d{4}-\d{2}-\d{2}/i, 'visible ISO as-of date');
    const links = await note.locator('a[href]').evaluateAll(nodes => nodes.map(el => el.getAttribute('href')));
    assert.ok(links.some(link => /^https:\/\//.test(link)), 'note has an https source link');
    noteLinks ??= links;
    assert.deepEqual(links, noteLinks, 'source links are stable');
    if (mode !== 'js') {
      const shown = page.locator('[data-predict-answer]');
      await count(shown, 2);
      for (const answer of await shown.all()) assert.equal(await answer.isVisible(), true);
      assert.deepEqual((await shown.allInnerTexts()).map(normal), answers, 'fallback contains the same explanations as Reveal');
      for (const button of await page.locator('[data-predict] button').all()) {
        if (mode === 'no-js') {
          await enabled(button, false);
          assert.notEqual(await button.getAttribute('disabled'), null, 'predict buttons are disabled in authored markup');
        }
        else assert.equal(await button.isVisible(), false, 'print hides interactive controls');
      }
      await screenshot(page, mode);
    }
  }
});

test('A1: isolated file:// page needs only itself, no network APIs, modules or vendor', { timeout: 60000 }, async t => {
  const source = await readFile(file, 'utf8');
  for (const obsolete of ['vendor', 'provenance.json', 'README.md']) {
    await assert.rejects(access(path.join(path.dirname(evidence), obsolete)), { code: 'ENOENT' }, `remove obsolete tokenizer/${obsolete}`);
  }
  const isolated = path.join(await scratch(t), 'tokenizer.html');
  await copyFile(file, isolated); // Deliberately copy no sibling assets or tooling.
  const url = pathToFileURL(isolated).href;
  const browser = await chromium.launch();
  const errors = [], requests = [], forbidden = [];
  t.after(async () => {
    await browser.close();
    assert.deepEqual(errors, [], 'offline page has no runtime or request errors');
    assert.deepEqual(forbidden, [], 'page never attempts a network/worker API, even if it catches the exception');
    assert.ok(requests.length > 0 && requests.every(request => request === url), 'every request is the HTML file itself');
  });
  const context = await browser.newContext({ offline: true, serviceWorkers: 'block', viewport: { width: 1440, height: 900 } });
  await context.exposeBinding('__recordForbiddenTokenizerAPI', (_, name) => forbidden.push(name));
  await context.addInitScript(() => {
    for (const name of ['fetch', 'XMLHttpRequest', 'WebSocket', 'EventSource', 'Worker']) {
      Object.defineProperty(window, name, { configurable: false, writable: false, value: function () {
        window.__recordForbiddenTokenizerAPI(name);
        throw new Error(`Offline tokenizer lab cannot use ${name}`);
      } });
    }
  });
  await context.route('**/*', route => route.request().url() === url ? route.continue() : route.abort());
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  page.on('request', request => requests.push(request.url()));
  page.on('requestfailed', request => errors.push(`request failed: ${request.url()}`));
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  await structure(page);
  await examples(page);
  await staticRuntime(page, source);
  await cycle(page, [false, true]);
  await cycle(page, [true, false], true);
  // One browser round trip drains the API binding calls before cleanup asserts.
  await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 0)));
});

test('A1/A2: suite is registered in both independent CI collection lists', async () => {
  assert.equal(suites.filter(suite => suite === 'tokenizer').length, 1);
  const pkg = JSON.parse(await readFile(path.join(repoRoot, 'setup/package.json'), 'utf8'));
  const argv = pkg.scripts.test.trim().split(/\s+/);
  assert.deepEqual(argv.slice(0, 2), ['node', '--test']);
  assert.equal(argv.slice(2).filter(arg => path.resolve(repoRoot, 'setup', arg) ===
    path.join(repoRoot, 'tools/html-pages/tests/tokenizer.test.mjs')).length, 1, 'npm test collects this suite exactly once');
});

test('A2: current page hash, byte count, PASS command and seven named view observations', { timeout: 60000 }, async t => {
  const [bytes, review] = await Promise.all([readFile(file), readFile(evidence, 'utf8')]);
  assert.ok(review.includes(hash(bytes)), 'review is bound to the final HTML sha256');
  const numeric = review.replace(/(?<=\d),(?=\d)/g, '');
  assert.ok(new RegExp(`\\b${bytes.length}\\s+bytes\\b|\\bbytes\\s*[:|]\\s*${bytes.length}\\b`, 'i').test(numeric) ||
    (/\|[^\n]*\bBytes\b[^\n]*\|/i.test(numeric) && new RegExp(`\\|[^\\n]*\\b${bytes.length}\\b[^\\n]*\\|`).test(numeric)),
  'review records the current HTML byte count');
  const commandIndex = review.indexOf(checkCommand);
  assert.ok(commandIndex >= 0, 'review records the exact reproducible check-page command');
  assert.match(review.slice(Math.max(0, commandIndex - 200), commandIndex + checkCommand.length + 600), /\bPASS\b/);
  const blocks = review.split(/\n\s*\n|\n(?=\s*(?:[-*+]\s|#{1,6}\s|\|))/).map(normal);
  const headings = [...review.matchAll(/^#{1,6}\s+.+$/gm)];
  for (const [i, heading] of headings.entries()) {
    blocks.push(normal(review.slice(heading.index, headings[i + 1]?.index ?? review.length)));
  }
  const views = [/\bdesktop\b/i, /\blaptop\b/i, /\bmobile\b/i, /\bno[- ]?(?:js|javascript)\b/i,
    /\bprint\b/i, /\breduced[- ]motion\b/i, /\b(?:predict[- ]revealed|revealed prediction|prediction revealed)\b/i];
  for (const view of views) {
    assert.ok(blocks.some(block => {
      const match = block.match(view);
      // A named paragraph, list item, table row or heading must carry its own
      // observation. A single line enumerating all seven names is insufficient.
      const observation = match && block.slice(match.index + match[0].length).replace(/^[\s\d×x()|:*-]+/, '');
      return match && match.index < 80 && /[A-Za-z]/.test(observation) &&
        views.every(other => !block.match(other) || block.match(other).index >= match.index);
    }),
      `named observation for ${view}, not just a list of view names`);
  }
  const page = await pageFor(t, { reducedMotion: 'reduce' });
  await structure(page);
  await examples(page);
  await screenshot(page, 'reduced-motion');
  await cycle(page, [true, true], true);
  // Verbatim quotations are regression evidence, not an automatic accuracy
  // judgement. The cross-vendor reviewer reads these and opens every PNG.
  const quoted = normal(review.replace(/^\s*>\s?/gm, ''));
  for (const locator of [page.locator('[data-tok-explain]'), page.locator('[data-tok-note]'),
    ...await page.locator('[data-predict-answer]').all()]) {
    assert.ok(quoted.includes(normal(await locator.textContent())), 'review quotes the explanation, note and both answers verbatim');
  }
  assert.doesNotMatch(review, /^#{1,6}\s+(?:Presets|Vendoring|Performance)\b/im, 'remove superseded live-tokenizer review sections');
});
