import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir, cp } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { cpus, platform, release } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import vm from 'node:vm';
import { chromium } from '../browser.mjs';
import { repoRoot, suites, openPage, eventually, scratch, chooseAll, initialPredict } from './component-helpers.mjs';

// Issue 28's agreed DOM contract. No page-private functions or tokenizer globals
// are used as the oracle. Reads happen inside tests, including prerequisite reads.
// Provenance nesting, JSON field spelling, and prose layout are not prescribed.
const relative = 'sessions/01-fundamentals/cursus/labs/tokenizer';
const file = path.join(repoRoot, `${relative}.html`);
const assetDir = path.join(repoRoot, relative);
const encodings = ['r50k_base', 'o200k_base'];
const requiredPresets = ['strawberry', 'optimization', 'bonjour', 'latex', 'python', 'number', 'mps', 'french'];
const tarball = 'https://registry.npmjs.org/gpt-tokenizer/-/gpt-tokenizer-3.4.0.tgz';
const normal = value => value.replace(/\s+/g, ' ').trim();
const sha256 = value => createHash('sha256').update(value).digest('hex');
const input = page => page.locator('textarea[data-tok-input]');
const radio = (page, encoding) => page.locator(`input[type=radio][name=encoding][value="${encoding}"]`);
const chips = page => page.locator('[data-tok-chips] [data-tok-chip]');
const ids = page => page.locator('[data-tok-ids] [data-tok-id]');

async function readRequired(filename, encoding = 'utf8') {
  try { return await readFile(filename, encoding); }
  catch (error) { assert.fail(`Required deliverable ${filename}: ${error.message}`); }
}
const readAsset = name => readRequired(path.join(assetDir, name));
async function pageFor(t, options = {}) {
  await readRequired(file);
  return openPage(t, chromium, { file, offline: true, ...options });
}
function section(markdown, heading) {
  const headings = [...markdown.matchAll(/^(#{1,6})\s+(.+)$/gm)];
  const found = headings.flatMap((h, i) => {
    if (!heading.test(h[2])) return [];
    const end = headings.slice(i + 1).find(next => next[1].length <= h[1].length)?.index ?? markdown.length;
    return [markdown.slice(h.index, end)];
  });
  assert.ok(found.length, `Required Markdown section: ${heading}`);
  return found.join('\n');
}
function integer(text, label) {
  assert.match(text.trim(), /^\d+$/, `${label}: an integer`);
  return Number(text.trim());
}
function idSequence(text) {
  assert.match(text.trim(), /^(?:\d+(?:\s+\d+)*)?$/, 'space-separated integer IDs');
  return text.trim() ? text.trim().split(/\s+/).map(Number) : [];
}
function generatedTexts() {
  let seed = 0x28c0ffee;
  const atoms = [' café', 'résoudre', '\n    ', '∑', 'x_17', '🍓', 'e\u0301', '<b>literal</b>', '123456789', '!?', '東京', '\t', ' the'];
  return Array.from({ length: 5 }, (_, i) => Array.from({ length: 29 + i * 13 }, () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return atoms[seed % atoms.length];
  }).join(''));
}
const examples = () => [' strawberry 🍓', 'café', 'e\u0301 a\u0308 👩🏽‍💻', '        \t\n  ', '<|endoftext|>', '',
  '<img src=x onerror="window.__tokInjection=true"><b>plain text</b>', ...generatedTexts()];

async function scriptPaths(page) {
  const scripts = await page.locator('script[src]').evaluateAll(nodes => nodes.map(n => ({ src: n.getAttribute('src'), type: n.getAttribute('type') })));
  assert.equal(scripts.length, 2, 'exactly the two external UMD scripts');
  return scripts.map(({ src, type }, i) => {
    assert.ok(src && !/^(?:[a-z][\w+.-]*:|\/|\\)/i.test(src), 'relative classic-script URL');
    assert.ok(!type || /^(?:text|application)\/javascript$/i.test(type), 'classic script');
    const resolved = fileURLToPath(new URL(src, page.url()));
    const directory = path.dirname(fileURLToPath(page.url()));
    assert.equal(resolved, path.join(directory, 'tokenizer', 'vendor', `${encodings[i]}.js`), 'specified vendor order and location');
    return resolved;
  });
}

async function loadOracle(t, filename) {
  const source = await readRequired(filename);
  const context = vm.createContext({ TextEncoder, TextDecoder, console });
  const before = new Set(Object.keys(context));
  try { vm.runInContext(source, context, { filename, timeout: 10000 }); }
  catch (error) {
    // Some otherwise-valid UMD wrappers require browser globals even at load time.
    if (error.name !== 'ReferenceError') throw error;
  }
  const names = Object.keys(context).filter(name => !before.has(name) &&
    typeof context[name]?.encode === 'function' && typeof context[name]?.decode === 'function');
  if (names.length) {
    assert.equal(names.length, 1, 'one independently loaded tokenizer global');
    context.__oracle = context[names[0]];
    return async (text, special = false) => {
      context.__text = text;
      context.__special = special;
      // Construct Set in the encoder's realm (UMD implementations may use instanceof).
      const result = vm.runInContext(`(() => {
        const ids = Array.from(__oracle.encode(__text, __special
          ? { allowedSpecial: new Set(['<|endoftext|>']) }
          : { disallowedSpecial: new Set() }));
        return { ids, pieces: ids.map(id => __oracle.decode([id])) };
      })()`, context, { timeout: 10000 });
      return { ids: Array.from(result.ids), pieces: Array.from(result.pieces) };
    };
  }
  // A browser-only UMD wrapper still gets a blank, isolated page, never the lab.
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const page = await browser.newPage({ offline: true });
  const oldNames = await page.evaluate(() => Object.keys(window));
  await page.addScriptTag({ path: filename });
  const name = await page.evaluate(old => {
    const found = Object.keys(window).filter(k => !old.includes(k) &&
      typeof window[k]?.encode === 'function' && typeof window[k]?.decode === 'function');
    if (found.length !== 1) throw new Error('Expected one standalone UMD tokenizer global');
    return found[0];
  }, oldNames);
  return (text, special = false) => page.evaluate(({ name, text, special }) => {
    const encoder = window[name];
    const ids = Array.from(encoder.encode(text, special
      ? { allowedSpecial: new Set(['<|endoftext|>']) } : { disallowedSpecial: new Set() }));
    return { ids, pieces: ids.map(id => encoder.decode([id])) };
  }, { name, text, special });
}
async function oracles(t, page) {
  const paths = await scriptPaths(page);
  const result = {};
  for (const [i, encoding] of encodings.entries()) result[encoding] = await loadOracle(t, paths[i]);
  return result;
}
async function rendered(page, text, expected) {
  await eventually(async () => {
    const actual = await page.evaluate(() => {
      const list = selector => [...document.querySelectorAll(selector)].map(n => ({
        id: n.getAttribute('data-token-id'), index: n.getAttribute('data-index'), text: n.textContent,
      }));
      return {
        chars: document.querySelector('output[data-tok-chars]')?.textContent,
        count: document.querySelector('output[data-tok-count]')?.textContent,
        chips: list('[data-tok-chips] [data-tok-chip]'), ids: list('[data-tok-ids] [data-tok-id]'),
      };
    });
    assert.equal(integer(actual.chars ?? '', 'characters'), [...text].length);
    assert.equal(integer(actual.count ?? '', 'tokens'), expected.ids.length);
    assert.deepEqual(actual.chips, expected.ids.map((id, i) => ({ id: String(id), index: String(i), text: expected.pieces[i] })));
    assert.deepEqual(actual.ids.map(n => ({ ...n, text: n.text.trim() })), expected.ids.map((id, i) => ({ id: String(id), index: String(i), text: String(id) })));
  }, 'render matches independent encoder');
}
async function fill(page, oracle, encoding, text) {
  await radio(page, encoding).check();
  await input(page).fill(text);
  const expected = await oracle[encoding](text);
  await rendered(page, text, expected);
  return expected;
}
async function presets(page) {
  const values = await page.locator('button[data-tok-preset]').evaluateAll(nodes => nodes.map(n => ({ key: n.dataset.tokPreset, value: n.getAttribute('value'), label: n.textContent.trim() })));
  assert.equal(new Set(values.map(p => p.key)).size, values.length, 'unique preset keys');
  for (const key of requiredPresets) assert.ok(values.some(p => p.key === key), `preset ${key}`);
  for (const p of values) {
    assert.ok(p.value?.trim(), `preset ${p.key} has a value`);
    assert.ok(p.label, `preset ${p.key} has a label`);
  }
  for (const [key, value] of Object.entries({ strawberry: ' strawberry', optimization: 'Optimization', bonjour: 'Bonjour' })) {
    assert.equal(values.find(p => p.key === key).value, value);
  }
  assert.ok(values.find(p => p.key === 'number').value.replace(/\D/g, '').length >= 12);
  return values;
}
async function clickPresets(page, oracle, values) {
  for (const encoding of encodings) {
    await radio(page, encoding).check();
    for (const [index, p] of values.entries()) {
      // Use authored button order, without CSS-escaping arbitrary extra keys.
      await page.locator('button[data-tok-preset]').nth(index).click();
      assert.equal(await input(page).inputValue(), p.value);
      assert.equal(await radio(page, encoding).isChecked(), true, 'preset preserves encoding');
      await rendered(page, p.value, await oracle[encoding](p.value));
    }
  }
}
async function activePair(page, index) {
  await eventually(async () => {
    for (const list of [chips(page), ids(page)]) {
      assert.deepEqual(await list.evaluateAll(nodes => nodes.filter(n => n.hasAttribute('data-active')).map(n => Number(n.dataset.index))), index === null ? [] : [index]);
    }
  }, 'only the matching occurrence is active');
}
async function styles(page) {
  return page.evaluate(() => ['[data-tok-chips] [data-tok-chip]', '[data-tok-ids] [data-tok-id]'].flatMap(selector =>
    [...document.querySelectorAll(selector)].map(n => {
      const s = getComputedStyle(n);
      return [s.outlineStyle, s.outlineWidth, s.boxShadow, s.backgroundColor];
    })));
}
async function linking(page, oracle, encoding = 'o200k_base') {
  const expected = await fill(page, oracle, encoding, 'the the the');
  assert.ok(new Set(expected.ids).size < expected.ids.length, 'exercise repeated IDs');
  assert.ok(expected.ids.length >= 3);
  await input(page).hover();
  await input(page).evaluate(n => n.blur());
  await activePair(page, null);
  const k = 1, neighbour = 2, n = expected.ids.length;
  for (const list of [chips(page), ids(page)]) {
    const before = await styles(page);
    await list.nth(k).hover();
    await activePair(page, k);
    await eventually(async () => {
      const after = await styles(page);
      for (const offset of [0, n]) {
        assert.notDeepEqual(after[offset + k], before[offset + k], 'visible highlight on both members');
        assert.deepEqual(after[offset + neighbour], before[offset + neighbour], 'neighbour unchanged');
      }
    });
    await input(page).hover();
    await activePair(page, null);
  }
  for (const list of [chips(page), ids(page)]) {
    const tabs = await list.evaluateAll(nodes => nodes.map(n => n.tabIndex));
    assert.equal(tabs.filter(x => x === 0).length, 1, 'one tab stop in each list');
    assert.ok(tabs.every(x => x === 0 || x === -1));
    // Start at index 1, so both directions have an unambiguous neighbour.
    await list.nth(1).focus();
    await activePair(page, 1);
    for (const [key, target] of [['ArrowRight', 2], ['ArrowLeft', 1]]) {
      await page.keyboard.press(key);
      assert.equal(await list.nth(target).evaluate(n => n === document.activeElement), true);
      await activePair(page, target);
      assert.deepEqual(await list.evaluateAll(nodes => nodes.map(n => n.tabIndex)), expected.ids.map((_, i) => i === target ? 0 : -1));
    }
  }
  await input(page).fill('fresh input');
  await rendered(page, 'fresh input', await oracle[encoding]('fresh input'));
  await activePair(page, null);
  await chips(page).first().hover();
  await activePair(page, 0);
  const otherEncoding = encodings.find(value => value !== encoding);
  await radio(page, otherEncoding).check();
  await rendered(page, 'fresh input', await oracle[otherEncoding]('fresh input'));
  await activePair(page, null);
}
async function predictionCycle(page) {
  const root = page.locator('[data-predict]');
  assert.equal(await root.count(), 1);
  assert.equal(await root.locator('[data-predict-question]').count(), 2);
  await initialPredict(root);
  await root.locator('[data-predict-question]').first().locator('input[data-correct]').check();
  assert.equal(await root.locator('[data-predict-lock]').isEnabled(), false, 'both questions required');
  await chooseAll(root);
  assert.equal(await root.locator('[data-predict-lock]').isEnabled(), true);
  assert.equal(await root.locator('[data-predict-reveal]').isEnabled(), false);
  await root.locator('[data-predict-lock]').click();
  for (const r of await root.locator('input[type=radio]').all()) assert.equal(await r.isDisabled(), true);
  await root.locator('[data-predict-reveal]').click();
  for (const answer of await root.locator('[data-predict-answer]').all()) assert.equal(await answer.isVisible(), true);
  const revealed = (await root.locator('[data-predict-answer]').allTextContents()).join(' ');
  assert.deepEqual((await root.locator('[data-predict-result]').allTextContents()).map(normal), ['Correct.', 'Correct.']);
  await root.locator('[data-predict-reset]').click();
  await initialPredict(root);
  return revealed;
}

test('D1: registered lab, labelled controls, neutral initial state and exact token rendering', async t => {
  const page = await pageFor(t);
  const oracle = await oracles(t, page);
  assert.equal(await page.locator('html').getAttribute('data-design-system'), 'cursus');
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'lab');
  assert.deepEqual(await page.locator('*').evaluateAll(nodes => nodes.flatMap(n => [...n.attributes].map(a => a.name)).filter(n => /^(?:data-lab$|data-budget|data-reset$)/.test(n))), []);
  assert.ok(suites.includes('tokenizer'), 'register tokenizer in component-helpers.mjs');
  const pkg = JSON.parse(await readRequired(path.join(repoRoot, 'setup/package.json')));
  assert.ok(pkg.scripts.test.split(/\s+/).includes('../tools/html-pages/tests/tokenizer.test.mjs'), 'register tokenizer in npm test');
  assert.equal(await input(page).count(), 1);
  assert.ok(await input(page).evaluate(n => [...n.labels].some(l => l.textContent.trim())), 'textarea has native label');
  assert.equal(await page.locator('input[name=encoding]').count(), 2);
  for (const [encoding, label] of [['r50k_base', 'GPT-2 (r50k_base)'], ['o200k_base', 'GPT-4o family (o200k_base)']]) {
    assert.equal(await radio(page, encoding).evaluate(n => !!n.closest('fieldset')), true);
    assert.equal(normal(await radio(page, encoding).evaluate(n => [...n.labels].map(l => l.textContent).join(' '))), label);
  }
  assert.equal(await page.evaluate(() => {
    const selectors = ['[data-predict]', '[data-tok-input]', '[data-tok-chips]', '[data-tok-ids]',
      'button[data-tok-preset]', 'table[data-tok-compare]', '[data-tok-note]', '[data-tok-weight]'];
    const nodes = selectors.map(s => document.querySelector(s));
    return nodes.every(Boolean) && nodes.slice(1).every((n, i) =>
      !!(nodes[i].compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING));
  }), true, 'prediction, playground, presets/table, note, then weight footer');
  assert.match(await page.locator('output[data-tok-chars]').evaluate(n => [...n.labels].map(l => l.textContent).join(' ') || n.getAttribute('aria-label') || n.parentElement.textContent), /characters/i);
  assert.equal(await radio(page, 'o200k_base').isChecked(), true);
  const initial = await input(page).inputValue();
  assert.ok(initial.trim(), 'neutral initial sentence');
  assert.doesNotMatch(initial, /strawberry|\br['’]s\b|count.{0,15}\br\b/i);
  await rendered(page, initial, await oracle.o200k_base(initial));
  for (const text of examples()) {
    await input(page).fill(text);
    for (const encoding of ['r50k_base', 'o200k_base']) {
      await radio(page, encoding).check();
      const expected = await oracle[encoding](text);
      await rendered(page, text, expected);
      assert.ok(!expected.ids.includes(encoding === 'r50k_base' ? 50256 : 199999), 'ordinary text emits no end-of-text special ID');
    }
  }
  assert.equal(await chips(page).locator('img, b, script').count(), 0, 'user markup remains literal text');
  assert.equal(await page.evaluate(() => window.__tokInjection === true), false);
  await fill(page, oracle, 'o200k_base', 'One two three four five six seven eight nine.');
  const colors = await chips(page).evaluateAll(nodes => nodes.map(n => getComputedStyle(n).backgroundColor));
  assert.ok(colors.length > 2);
  for (let i = 1; i < colors.length; i++) assert.notEqual(colors[i], colors[i - 1], 'adjacent chips differ');
});

test('D1: hover and roving keyboard focus link occurrences visibly in both directions', async t => {
  const page = await pageFor(t);
  const oracle = await oracles(t, page);
  for (const encoding of encodings) await linking(page, oracle, encoding);
});

test('D2: every preset and both static comparison columns match the independent encoders', async t => {
  const page = await pageFor(t);
  const oracle = await oracles(t, page);
  const values = await presets(page);
  await clickPresets(page, oracle, values);
  const noJS = await pageFor(t, { javaScriptEnabled: false });
  assert.deepEqual(await presets(noJS), values, 'authored preset values');
  for (const view of [page, noJS]) {
    const rows = view.locator('table[data-tok-compare] tr[data-tok-preset-row]');
    assert.equal(await view.locator('table[data-tok-compare]').isVisible(), true);
    assert.equal(await rows.count(), values.length);
    const keys = await rows.evaluateAll(nodes => nodes.map(n => n.dataset.tokPresetRow));
    for (const p of values) {
      assert.equal(keys.filter(k => k === p.key).length, 1, `comparison row ${p.key}`);
      const actualRow = rows.nth(keys.indexOf(p.key));
      for (const encoding of encodings) {
        const cell = actualRow.locator(`td[data-encoding="${encoding}"]`);
        const expected = await oracle[encoding](p.value);
        assert.equal(integer(await cell.locator('[data-tok-compare-count]').textContent(), 'comparison count'), expected.ids.length);
        assert.deepEqual(idSequence(await cell.locator('[data-tok-compare-ids]').textContent()), expected.ids);
      }
    }
  }
  const evidence = section(await readAsset('review.md'), /presets/i);
  for (const p of values) assert.ok(normal(evidence).includes(normal(p.value)) || evidence.includes(JSON.stringify(p.value)), `review quotes ${p.key}`);
});

test('D3: prediction precedes spoilers, uses oracle answers, locks, reveals and resets', async t => {
  const page = await pageFor(t);
  const oracle = await oracles(t, page);
  const root = page.locator('[data-predict]');
  assert.equal(await root.count(), 1);
  assert.equal(await root.evaluate(n => ['[data-tok-input]', 'table[data-tok-compare]'].every(s => {
    const other = document.querySelector(s);
    return other && !!(n.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_FOLLOWING);
  })), true, 'prediction comes before playground and table');
  const questions = root.locator('fieldset[data-predict-question]');
  assert.equal(await questions.count(), 2);
  const q1 = questions.nth(0), q2 = questions.nth(1);
  assert.match(await q1.locator('legend').textContent(), /strawberry/i);
  assert.match(await q1.locator('legend').textContent(), /o200k(?:_base)?/i);
  assert.match(await q2.locator('legend').textContent(), /\br(?:['’]s|s)?\b/i);
  for (const q of [q1, q2]) assert.equal(await q.locator('input[type=radio][data-correct]').count(), 1);
  const label = q => q.locator('input[data-correct]').evaluate(n => [...n.labels].map(l => l.textContent).join(' '));
  const o200k = await oracle.o200k_base(' strawberry');
  assert.match(await label(q1), new RegExp(`\\b${o200k.ids.length}\\b`));
  assert.match(await label(q2), /\b(?:0|zero|none)\b/i);
  const revealed = await predictionCycle(page);
  const noJS = await pageFor(t, { javaScriptEnabled: false });
  const answers = noJS.locator('[data-predict-answer]');
  assert.equal(await answers.count(), 2);
  for (const answer of await answers.all()) assert.equal(await answer.isVisible(), true);
  const answerText = (await answers.allTextContents()).join(' ');
  assert.equal(normal(revealed), normal(answerText), 'revealed answers agree with authored no-JS answers');
  for (const encoding of encodings) {
    const expected = await oracle[encoding](' strawberry');
    assert.ok(answerText.includes(encoding), `answer identifies ${encoding}`);
    for (const id of expected.ids) assert.match(answerText, new RegExp(`\\b${id}\\b`));
    for (const piece of expected.pieces) assert.ok(normal(answerText).includes(normal(piece)), 'answer shows decoded pieces');
  }
  assert.match(answerText, /(?:\b3\b|\bthree\b)[\s\S]{0,60}\br(?:['’]s|s)?\b/i);
});

test('D4: Claude qualification is static, visible in all modes, sourced and quoted in review', async t => {
  let text;
  for (const options of [{}, { javaScriptEnabled: false }, { media: 'print' }]) {
    const { media, ...contextOptions } = options;
    const page = await pageFor(t, contextOptions);
    if (media) await page.emulateMedia({ media });
    const note = page.locator('[data-tok-note]');
    assert.equal(await note.count(), 1);
    assert.equal(await note.isVisible(), true);
    const current = normal(await note.textContent());
    text ??= current;
    assert.equal(current, text, 'same static qualification in JS, no-JS and print');
    assert.match(current, /Claude/i);
    assert.match(current, /as of\s+[^.!?]*\b\d{4}\b/i);
    assert.ok(await note.locator('a[href^="https://"]').count() > 0);
  }
  const quote = section(await readAsset('review.md'), /Claude note/i).replace(/^\s*>\s?/gm, '');
  assert.ok(normal(quote).includes(text), 'verbatim note in review');
});

function objects(value, trail = '') {
  if (!value || typeof value !== 'object') return [];
  return [{ value, trail }, ...Object.entries(value).flatMap(([k, v]) => objects(v, `${trail}/${k}`))];
}
function strings(value) {
  if (typeof value === 'string') return [value];
  return value && typeof value === 'object' ? Object.values(value).flatMap(strings) : [];
}
function provenanceRecord(meta, filename) {
  const found = objects(meta).filter(({ value, trail }) => /^[a-f\d]{64}$/i.test(value.sha256 ?? '') &&
    (trail + ' ' + Object.values(value).filter(v => typeof v === 'string').join(' ')).includes(filename));
  assert.equal(found.length, 1, `one provenance record for ${filename}`);
  return found[0];
}
test('D5: two pinned classic UMD encoders, identity anchors, license and provenance evidence', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  const paths = await scriptPaths(page);
  const oracle = await oracles(t, page);
  const meta = JSON.parse(await readAsset('provenance.json'));
  const sharedFacts = strings(meta);
  const review = section(await readAsset('review.md'), /vendoring provenance/i);
  assert.deepEqual((await readdir(path.join(assetDir, 'vendor'))).sort(), ['LICENSE', 'o200k_base.js', 'r50k_base.js'], 'only the two encodings and license, no source maps');
  for (const [i, encoding] of encodings.entries()) {
    const bytes = await readRequired(paths[i], null), source = bytes.toString('utf8');
    assert.match(source, /typeof\s+exports|typeof exports|"object"\s*==\s*typeof exports|'object'\s*==\s*typeof exports/, 'UMD CommonJS arm');
    assert.match(source, /define\.amd/, 'UMD AMD arm');
    assert.doesNotMatch(source, /^\s*(?:import\s|export\s)/m, 'no ESM statements');
    assert.deepEqual((await oracle[encoding]('<|endoftext|>', true)).ids, [i === 0 ? 50256 : 199999]);
    if (i === 0) assert.deepEqual((await oracle[encoding]('Hello world')).ids, [15496, 995]);
    const ordinary = [];
    for (const text of [...examples(), '        ', 'Bonjour Optimization strawberry contraintes tokenizer 東京 中文 العربية']) ordinary.push(...(await oracle[encoding](text)).ids);
    assert.ok(ordinary.every(id => Number.isInteger(id) && id >= 0));
    if (i === 0) assert.ok(ordinary.every(id => id < 50256), 'r50k ordinary vocabulary, excludes p50k and special IDs');
    else {
      assert.ok(ordinary.some(id => id > 100000), 'o200k large vocabulary');
      assert.ok(ordinary.every(id => id < 199999), 'ordinary o200k IDs');
    }
    const { value } = provenanceRecord(meta, `${encoding}.js`);
    assert.equal(value.sha256, sha256(bytes));
    const byteValues = Object.entries(value).filter(([k]) => /bytes|byte.?count|byte.?length|^size$|^length$/i.test(k)).map(([, v]) => v);
    assert.ok(byteValues.includes(bytes.length), 'exact vendored byte count');
    assert.ok(strings(value).includes(`package/dist/${encoding}.js`), 'source path in tarball');
    assert.ok(sharedFacts.includes('gpt-tokenizer') || sharedFacts.includes('gpt-tokenizer@3.4.0'));
    assert.ok(sharedFacts.includes('3.4.0') || sharedFacts.includes('gpt-tokenizer@3.4.0'));
    assert.ok(sharedFacts.includes(tarball), 'registry tarball URL');
    assert.ok(sharedFacts.some(s => /^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(s)), 'retrieval date');
    const integrity = sharedFacts.find(s => /^sha(?:256|384|512)-[A-Za-z\d+/]+={0,2}$/.test(s));
    assert.ok(integrity, 'npm integrity');
    const mapFields = Object.entries(value).filter(([k]) => /source.?map/i.test(k));
    assert.ok(mapFields.length, 'sourceMappingURL presence recorded');
    const hasMap = /\/\/[#@]\s*sourceMappingURL\s*=/.test(source);
    assert.ok(mapFields.some(([, v]) => v === hasMap || (typeof v === 'object' && v && Object.values(v).includes(hasMap))), 'source map presence matches file');
    assert.ok(review.includes(sha256(bytes)), 'npm pack evidence contains committed hash');
    assert.ok(review.includes(integrity), 'npm pack evidence contains registry integrity');
  }
  assert.match(review, /npm pack/);
  const license = await readAsset('vendor/LICENSE');
  assert.match(license, /MIT/);
  assert.match(license, /Permission is hereby granted/);
  const readme = await readAsset('README.md');
  assert.match(readme, /3\.4\.0/);
  assert.match(readme, /(?:v(?:ersion\s*)?4|4\.0)[\s\S]{0,160}(?:UMD)|UMD[\s\S]{0,160}(?:v(?:ersion\s*)?4|4\.0)/i);
  assert.match(readme, /npm pack gpt-tokenizer@3\.4\.0/);
  const setup = await readRequired(path.join(repoRoot, 'setup/README.md'));
  assert.match(setup, /npm pack gpt-tokenizer@3\.4\.0/);
  assert.match(setup, /--ignore-scripts/);
  assert.match(setup, /tokenizer\/vendor/);
  const footer = page.locator('footer').filter({ has: page.locator('[data-tok-weight]') });
  assert.match(await footer.textContent(), /gpt-tokenizer[\s\S]*3\.4\.0/);
  assert.match(await footer.textContent(), /MIT/);
  const links = await footer.locator('a[href]').evaluateAll(nodes => nodes.map(n => n.getAttribute('href')));
  assert.ok(links.some(href => !/^(?:[a-z][\w+.-]*:|\/)/i.test(href) && fileURLToPath(new URL(href, pathToFileURL(file))) === path.join(assetDir, 'vendor/LICENSE')), 'relative vendored LICENSE credit');
});

test('A1: isolated file copy uses no network APIs while all controls work offline', async t => {
  await readRequired(file);
  const dir = await scratch(t), copy = path.join(dir, 'tokenizer.html');
  await cp(file, copy);
  await cp(assetDir, path.join(dir, 'tokenizer'), { recursive: true });
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const context = await browser.newContext({ offline: true });
  const remote = [], requests = [], errors = [];
  await context.route(/^(?:https?|wss?):/i, route => { remote.push(route.request().url()); return route.abort(); });
  await context.addInitScript(() => {
    window.__networkCalls = [];
    for (const [object, key, label] of [[window, 'fetch', 'fetch'], [XMLHttpRequest.prototype, 'open', 'XHR'], [navigator, 'sendBeacon', 'sendBeacon']]) {
      const original = object[key];
      object[key] = function (...args) { window.__networkCalls.push(label); return Reflect.apply(original, this, args); };
    }
    window.WebSocket = new Proxy(window.WebSocket, {
      construct(target, args) { window.__networkCalls.push('WebSocket'); return Reflect.construct(target, args); },
    });
  });
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  page.on('request', request => requests.push(request.url()));
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(pathToFileURL(copy).href);
  const inline = await page.locator('script:not([src])').allTextContents();
  for (const source of inline) assert.doesNotMatch(source, /\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|\bimport\s*\(/);
  const oracle = await oracles(t, page);
  await clickPresets(page, oracle, await presets(page));
  for (const encoding of encodings) await linking(page, oracle, encoding);
  await predictionCycle(page);
  assert.deepEqual(await page.evaluate(() => window.__networkCalls), [], 'including caught network API calls');
  assert.deepEqual(remote, []);
  assert.deepEqual(errors, []);
  assert.ok(requests.length >= 3, 'HTML and both local scripts requested');
  for (const url of requests) {
    assert.equal(new URL(url).protocol, 'file:', 'every request is local');
    const local = path.relative(dir, fileURLToPath(url));
    assert.ok(local && !local.startsWith(`..${path.sep}`) && local !== '..' && !path.isAbsolute(local), 'request stays inside isolated copy');
  }
});

function corpora() {
  const seeds = {
    prose: 'Bonjour, où sont les contraintes du modèle ? Un café près de la rivière. A small bird follows the quiet path. ',
    code: 'def objective(x):\n    return sum(c * v for c, v in zip(costs, x))\n\\sum_{j=1}^{n} a_{ij} x_j \\le b_i\n',
    numbers: '12345678901234567890 9876543210,.;:!? +-*/=()[]{} 0.000123 42% #7 | 555_012_345\n',
  };
  return Object.entries(seeds).map(([name, seed]) => [name, [...seed.repeat(Math.ceil(2000 / [...seed].length))].slice(0, 2000).join('')]);
}
test('A1: every one of 120 real input-to-layout samples is below 50 ms', async t => {
  await readRequired(file);
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const context = await browser.newContext({ offline: true, viewport: { width: 1440, height: 900 } });
  const errors = [];
  await context.route(/^(?:https?|wss?):/i, route => { errors.push(route.request().url()); return route.abort(); });
  await context.addInitScript(() => {
    window.__samples = [];
    window.__expected = null;
    let start;
    window.addEventListener('input', event => {
      if (event.target.matches('textarea[data-tok-input]') && window.__expected) start = performance.now();
    }, true);
    window.addEventListener('input', event => {
      if (!event.target.matches('textarea[data-tok-input]') || !window.__expected) return;
      const expected = window.__expected, began = start;
      const observe = () => {
        const matches = (selector, visible = false) => {
          const nodes = [...document.querySelectorAll(selector)];
          return nodes.length === expected.length && nodes.every((n, i) => n.getAttribute('data-token-id') === String(expected[i]) && (!visible || n.textContent.trim() === String(expected[i])));
        };
        const count = document.querySelector('[data-tok-count]')?.textContent.trim();
        if (matches('[data-tok-chips] [data-tok-chip]') && matches('[data-tok-ids] [data-tok-id]', true) && count === String(expected.length)) {
          void document.body.offsetHeight;
          window.__samples.push(performance.now() - began);
        } else if (performance.now() - began >= 1000) window.__samples.push({ timeout: true });
        else requestAnimationFrame(observe);
      };
      requestAnimationFrame(observe);
    });
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(pathToFileURL(file).href);
  const oracle = await oracles(t, page);
  t.diagnostic(`CPU: ${cpus()[0]?.model ?? 'unknown'}; OS: ${platform()} ${release()}; browser: ${browser.version()}; no CPU throttling`);
  const all = [];
  for (const [name, corpus] of corpora()) for (const encoding of encodings) {
    assert.equal([...corpus].length, 2000);
    await page.evaluate(() => { window.__expected = null; window.__samples = []; });
    await fill(page, oracle, encoding, corpus);
    await input(page).focus();
    await input(page).evaluate(n => n.setSelectionRange(n.value.length, n.value.length));
    let text = corpus;
    for (let i = 0; i < 20; i++) {
      const char = ['a', 'é', '7', ' ', '!'][i % 5];
      text += char;
      const expected = await oracle[encoding](text);
      await page.evaluate(ids => { window.__expected = ids; }, expected.ids);
      await page.keyboard.type(char);
      await page.waitForFunction(n => window.__samples.length >= n, i + 1, { timeout: 3000 });
    }
    const samples = await page.evaluate(() => window.__samples);
    all.push(...samples);
    const numeric = samples.filter(Number.isFinite).sort((a, b) => a - b);
    const median = numeric.length === 20 ? (numeric[9] + numeric[10]) / 2 : null;
    t.diagnostic(JSON.stringify({ corpus: name, encoding, n: samples.length, samples, median_ms: median, max_ms: numeric.length ? Math.max(...numeric) : null }));
    assert.equal(samples.length, 20, 'one sample per real keystroke');
    await rendered(page, text, await oracle[encoding](text));
  }
  assert.deepEqual(errors, []);
  assert.equal(all.length, 120, 'no warm-up exclusion or discarded samples');
  assert.ok(all.every(ms => Number.isFinite(ms) && ms >= 0 && ms < 50), `Every sample must be <50 ms; failures: ${JSON.stringify(all.filter(ms => !Number.isFinite(ms) || ms >= 50))}`);
  const performance = section(await readAsset('review.md'), /performance/i);
  for (const label of [/CPU|processor/i, /\bOS\b|operating system/i, /browser|Chromium/i, /\bn\b|samples/i, /median/i, /max/i, /r50k_base/, /o200k_base/]) assert.match(performance, label);
  assert.ok((performance.match(/\b\d+(?:\.\d+)?\b/g) ?? []).length >= 18, 'six corpus/encoding rows of n, median and max');
});

test('A2: documented raw page weight matches each file, o200k subtotal and full total', async t => {
  const names = ['tokenizer.html', 'r50k_base.js', 'o200k_base.js'];
  const paths = [file, ...encodings.map(e => path.join(assetDir, 'vendor', `${e}.js`))];
  const sizes = [];
  for (const filename of paths) sizes.push((await readRequired(filename, null)).length);
  const weight = section(await readAsset('README.md'), /page weight/i);
  const lines = weight.split('\n').map(line => line.replace(/(?<=\d)[,_\u202f](?=\d)/g, ''));
  const contains = (line, value) => new RegExp(`(?<![\\d.])${value}(?![\\d.])`).test(line);
  for (const [i, name] of names.entries()) assert.ok(lines.some(line => line.includes(name) && contains(line, sizes[i])), `exact byte count for ${name}`);
  const subtotal = sizes[0] + sizes[2], total = sizes.reduce((a, b) => a + b, 0);
  assert.ok(lines.some(line => /o200k|subtotal/i.test(line) && contains(line, subtotal)), 'o200k-only HTML + script subtotal');
  assert.ok(lines.some(line => /total/i.test(line) && contains(line, total)), 'full raw-byte total');
  assert.match(weight, /\bMB\b/);
  for (const value of [subtotal, total]) {
    const row = lines.find(line => contains(line, value));
    const decimals = [...row.matchAll(/\b(\d+)\.(\d+)\b/g)];
    assert.ok(decimals.some(m => Math.abs(Number(m[0]) - value / 1e6) <= 0.5 * 10 ** -m[2].length + 1e-10), 'decimal MB value for subtotal and total');
  }
  const page = await pageFor(t);
  const display = page.locator('[data-tok-weight]');
  assert.equal(await display.isVisible(), true);
  const shown = (await display.textContent()).match(/\b(\d+\.\d)\s*MB\b/i);
  assert.ok(shown, 'page displays total MB to one decimal');
  assert.ok(Math.abs(Number(shown[1]) - total / 1e6) <= 0.05, 'visible total matches raw bytes');
});

test('A3: screenshot and content review is bound to all three current file hashes', async () => {
  const review = await readAsset('review.md');
  for (const filename of [file, ...encodings.map(e => path.join(assetDir, 'vendor', `${e}.js`))]) {
    assert.ok(review.includes(sha256(await readRequired(filename, null))), `current review hash for ${path.basename(filename)}`);
  }
  for (const heading of [/presets/i, /Claude note/i, /vendoring provenance/i, /performance/i]) section(review, heading);
  const shots = section(review, /screenshots/i);
  for (const label of [/desktop/i, /laptop/i, /mobile/i, /no[- ](?:JS|JavaScript)|without JavaScript/i,
    /print/i, /reduced[- ]motion/i, /r50k/i, /o200k/i, /hover/i, /reveal/i,
    /2[,. ]?000[- ]character/i, /whitespace/i, /wrap/i, /overflow/i]) assert.match(shots, label);
});
