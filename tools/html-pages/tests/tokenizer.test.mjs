import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, readdir, cp, mkdir } from 'node:fs/promises';
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
const screenshotDir = path.join(repoRoot, 'artifacts/html-pages/tokenizer');
const encodings = ['r50k_base', 'o200k_base'];
const requiredPresets = ['strawberry', 'optimization', 'bonjour', 'latex', 'python', 'number', 'mps', 'french'];
const tarball = 'https://registry.npmjs.org/gpt-tokenizer/-/gpt-tokenizer-3.4.0.tgz';
const normal = value => value.replace(/\s+/g, ' ').trim();
const sha256 = value => createHash('sha256').update(value).digest('hex');
const input = page => page.locator('textarea');
const radio = (page, encoding) => page.locator(`input[type=radio][name=encoding][value="${encoding}"]`);
const chips = page => page.locator(':is([data-tok-chip], [data-chip]):not(table *)');
const ids = page => page.locator(':is([data-tok-id], [data-id-of]):not(table *)');
const presetButtons = page => page.locator('button[data-tok-preset], button[data-preset]');

async function screenshot(page, name) {
  await mkdir(screenshotDir, { recursive: true });
  await page.screenshot({ path: path.join(screenshotDir, `${name}.png`), fullPage: true });
}

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
const examples = () => [' strawberry 🍓', '🍓🍓 日本語', 'Ça coûte 3 € — où ?', 'café', 'é', '�',
  '\uFEFF', '\uFEFFabc', 'a\uFEFFb', 'e\u0301 a\u0308 👩🏽‍💻', '        \t\n  ', '<|endoftext|>', '',
  '<img src=x onerror="window.__tokInjection=true"><b>plain text</b>', ...generatedTexts()];

async function scriptPaths(page) {
  const scripts = await page.locator('script[src]').evaluateAll(nodes => nodes.map(n => ({ src: n.getAttribute('src'), type: n.getAttribute('type') })));
  assert.equal(scripts.length, 2, 'exactly the two external UMD scripts');
  const paths = scripts.map(({ src, type }) => {
    assert.ok(src && !/^(?:[a-z][\w+.-]*:|\/|\\)/i.test(src), 'relative classic-script URL');
    assert.ok(!type || /^(?:text|application)\/javascript$/i.test(type), 'classic script');
    const resolved = fileURLToPath(new URL(src, page.url()));
    const directory = path.dirname(fileURLToPath(page.url()));
    assert.ok(encodings.some(e => resolved === path.join(directory, 'tokenizer', 'vendor', `${e}.js`)), 'specified vendored script location');
    return resolved;
  });
  assert.equal(new Set(paths).size, 2, 'load both encodings, with no duplicate script');
  return encodings.map(e => paths.find(filename => path.basename(filename) === `${e}.js`));
}

// UTF-8 validity, rather than a copied page algorithm, chooses the shortest
// whole-character groups. Fresh fatal decoders reject incomplete token runs;
// ignoreBOM preserves a real leading U+FEFF. No library decode calls here.
function statelessDecoder(encoder) {
  const core = encoder.bytePairEncodingCoreProcessor;
  assert.equal(typeof core?.tryDecodeToken, 'function', 'pinned UMD exposes raw rank entries');
  const tokenBytes = id => {
    const entry = core.tryDecodeToken(id);
    assert.ok(entry !== undefined && entry !== null, `raw bytes for token ${id}`);
    return typeof entry === 'string' ? new TextEncoder().encode(entry) : Uint8Array.from(entry);
  };
  const decodeIds = ids => {
    const parts = ids.map(tokenBytes);
    const bytes = new Uint8Array(parts.reduce((n, part) => n + part.length, 0));
    let offset = 0;
    for (const part of parts) { bytes.set(part, offset); offset += part.length; }
    return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
  };
  const groupIds = ids => {
    const groups = [];
    let pending = [];
    for (const id of ids) {
      pending.push(id);
      let text;
      try { text = decodeIds(pending); }
      catch (error) {
        if (error.code === 'ERR_ENCODING_INVALID_ENCODED_DATA') continue;
        throw error;
      }
      groups.push({ ids: pending, text });
      pending = [];
    }
    assert.equal(pending.length, 0, 'encoded text ends on a complete UTF-8 character');
    return groups;
  };
  return { decodeIds, groupIds };
}

async function loadOracle(t, filename) {
  const source = await readRequired(filename);
  const context = vm.createContext({ TextEncoder, TextDecoder, console });
  const before = new Set(Object.keys(context));
  vm.runInContext(source, context, { filename, timeout: 10000 });
  const names = Object.keys(context).filter(name => !before.has(name) &&
    typeof context[name]?.encode === 'function' && typeof context[name]?.decode === 'function');
  assert.equal(names.length, 1, 'one independently loaded tokenizer global');
  context.__oracle = context[names[0]];
  const { decodeIds, groupIds } = statelessDecoder(context.__oracle);
  const encode = (text, special = false) => {
    context.__text = text;
    context.__special = special;
    // Construct Set in the encoder's realm (UMD uses instanceof).
    return Array.from(vm.runInContext(`__oracle.encode(__text, __special
      ? { allowedSpecial: new Set(['<|endoftext|>']) }
      : { disallowedSpecial: new Set() })`, context, { timeout: 10000 }));
  };
  // Self-test before this oracle supplies any expected page output. An
  // incomplete emoji ID must neither poison a later decode nor erase a BOM.
  const stable = encode('\uFEFFhello world');
  const first = decodeIds(stable);
  const emoji = encode('🍓');
  assert.ok(emoji.length > 1, 'exercise a split-byte character');
  assert.throws(() => decodeIds(emoji.slice(0, 1)), { code: 'ERR_ENCODING_INVALID_ENCODED_DATA' });
  assert.equal(decodeIds(stable), first, 'oracle is independent of prior partial-byte decoding');
  assert.equal(first, '\uFEFFhello world', 'oracle preserves a literal leading U+FEFF');
  const oracle = async (text, special = false) => {
    const ids = encode(text, special);
    const groups = groupIds(ids);
    return { ids, groups, pieces: groups.map(group => group.text) };
  };
  oracle.decodeIds = decodeIds;
  return oracle;
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
      return {
        chars: document.querySelector('output[data-tok-chars]')?.textContent,
        count: document.querySelector('output[data-tok-count]')?.textContent,
        chips: [...document.querySelectorAll(':is([data-tok-chip], [data-chip]):not(table *)')].map(n => ({
          ids: n.getAttribute('data-token-ids') ?? n.getAttribute('data-ids'),
          index: n.getAttribute('data-index'), text: n.getAttribute('data-text'),
          badge: n.getAttribute('data-token-count'),
          display: n.textContent,
          after: getComputedStyle(n, '::after').content,
          before: getComputedStyle(n, '::before').content,
          label: n.getAttribute('aria-label'),
        })),
        ids: [...document.querySelectorAll(':is([data-tok-id], [data-id-of]):not(table *)')].map(n => ({
          id: n.getAttribute('data-token-id') ?? n.textContent.trim(), index: n.getAttribute('data-index'), text: n.textContent.trim(),
          chip: n.getAttribute('data-chip-index') ?? n.getAttribute('data-id-of'),
        })),
      };
    });
    assert.equal(integer(actual.chars ?? '', 'characters'), [...text].length);
    assert.equal(integer(actual.count ?? '', 'tokens'), expected.ids.length);
    assert.deepEqual(actual.chips.map(n => ({ ids: idSequence(n.ids ?? ''), index: n.index, text: n.text })),
      expected.groups.map((g, i) => ({ ids: g.ids, index: String(i), text: g.text })), 'shortest whole-character groups');
    assert.equal(actual.chips.map(n => n.text).join(''), text, 'chip texts rebuild the exact input, including U+FEFF');
    assert.deepEqual(actual.chips.flatMap(n => idSequence(n.ids)), expected.ids, 'no lost token boundary');
    const tokenChips = expected.groups.flatMap((g, i) => g.ids.map(() => String(i)));
    assert.deepEqual(actual.ids.map(({ index, ...id }) => id), expected.ids.map((id, i) => ({ id: String(id), text: String(id), chip: tokenChips[i] })), 'one ID span per token');
    for (const [i, id] of actual.ids.entries()) if (id.index !== null) assert.equal(id.index, String(i), 'authored token index');
    for (const [i, group] of expected.groups.entries()) {
      const display = actual.chips[i].display;
      const displayVariants = [display];
      if (group.ids.length > 1) displayVariants.push(display.replace(new RegExp(`×\\s*${group.ids.length}\\b`), ''));
      const unmark = value => value.replace(/↵\n?/g, '\n').replaceAll('␣', ' ').replaceAll('→', '\t');
      assert.ok(displayVariants.some(value => value === group.text || unmark(value) === group.text),
        'visible chip text represents the raw decoded text, with optional whitespace marks and badge');
      const label = actual.chips[i].label ?? '';
      assert.match(label, /IDs/i, 'chip has an accessible text/IDs label');
      for (const id of group.ids) assert.match(label, new RegExp(`\\b${id}\\b`));
      assert.ok(normal(label).includes(normal(group.text)), 'chip label includes its text');
      if (group.ids.length === 1) continue;
      assert.match(group.text, /[^\x00-\x7F]/, 'only split Unicode characters group tokens');
      const chip = actual.chips[i];
      const badgeText = `${chip.display} ${chip.before} ${chip.after}`.replace(/["']/g, '');
      assert.match(badgeText, new RegExp(`×\\s*${group.ids.length}\\b`), 'visible ×n badge (DOM or CSS)');
      if (chip.badge !== null) assert.equal(chip.badge, String(group.ids.length));
    }
    if (/^[\x00-\x7F]*$/.test(text)) assert.equal(actual.chips.length, expected.ids.length, 'ASCII keeps one chip per token');
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
  const authored = await presetButtons(page).evaluateAll(nodes => nodes.map(n => ({
    value: n.getAttribute('data-preset') ?? n.getAttribute('value'),
    label: n.getAttribute('aria-label') || n.textContent.trim(),
  })));
  const values = authored.map(p => ({ ...p, key: requiredPresets.find(key => new RegExp(key, 'i').test(p.label)) }));
  assert.equal(new Set(values.map(p => p.key)).size, values.length, 'unique preset keys');
  for (const key of requiredPresets) assert.ok(values.some(p => p.key === key), `preset ${key}`);
  for (const p of values) {
    assert.ok(p.value?.trim(), `preset ${p.key} has a value`);
    assert.ok(p.label, `preset ${p.key} has a label`);
  }
  for (const [key, value] of Object.entries({ strawberry: ' strawberry', optimization: 'Optimization', bonjour: 'Bonjour' })) {
    assert.equal(values.find(p => p.key === key).value, value);
  }
  assert.equal(values.length, 8, 'eight authored presets');
  for (const [key, name] of Object.entries({ strawberry: /strawberry/i, optimization: /Optimization/i,
    bonjour: /Bonjour/i, latex: /LaTeX/i, python: /Python/i, number: /number/i, mps: /MPS/i, french: /French/i })) {
    assert.match(values.find(p => p.key === key).label, name, 'preset name identifies its category');
  }
  const value = key => values.find(p => p.key === key).value;
  assert.match(value('latex'), /\\[A-Za-z]+/);
  assert.match(value('latex'), /\\(?:le|ge)(?:q)?\b|=/, 'LaTeX relation');
  assert.match(value('python'), /\b(?:def\s|import\s)/);
  assert.match(value('number'), /^\d{20,}$/, 'at least twenty digits');
  assert.match(value('mps'), /^\s*\S+\s+\S+\s+[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?:\s|$)/, 'MPS name, name, coefficient');
  assert.match(value('french'), /[àâçéèêëîïôùûüÿœ]/i, 'French accented letter');
  return values;
}
async function clickPresets(page, oracle, values) {
  for (const encoding of encodings) {
    await radio(page, encoding).check();
    for (const [index, p] of values.entries()) {
      // Use authored button order, without CSS-escaping arbitrary extra keys.
      await presetButtons(page).nth(index).click();
      assert.equal(await input(page).inputValue(), p.value);
      assert.equal(await radio(page, encoding).isChecked(), true, 'preset preserves encoding');
      await rendered(page, p.value, await oracle[encoding](p.value));
    }
  }
}
async function activePair(page, index, tokenIndex = null) {
  await eventually(async () => {
    assert.deepEqual(await chips(page).evaluateAll(nodes => nodes.filter(n =>
      n.hasAttribute('data-active') || n.hasAttribute('data-linked')).map(n => Number(n.dataset.index))), index === null ? [] : [index]);
    const linkedIds = await ids(page).evaluateAll(nodes => nodes.flatMap((n, i) =>
      n.hasAttribute('data-active') || n.hasAttribute('data-linked') ? [i] : []));
    const expectedIds = index === null ? [] : tokenIndex !== null ? [tokenIndex] : await ids(page).evaluateAll((nodes, index) => nodes.flatMap((n, i) =>
      Number(n.getAttribute('data-chip-index') ?? n.getAttribute('data-id-of')) === index ? [i] : []), index);
    assert.deepEqual(linkedIds, expectedIds, 'chip links its IDs; an ID links itself and its chip');
  }, 'only the matching occurrence group is active');
}
async function styles(page) {
  return page.evaluate(() => [':is([data-tok-chip], [data-chip]):not(table *)', ':is([data-tok-id], [data-id-of]):not(table *)'].flatMap(selector =>
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
    for (const [key, target] of [['ArrowRight', 2], ['ArrowLeft', 1], ['End', n - 1], ['Home', 0]]) {
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

test('D1: stateless oracle survives partial-byte decodes and preserves literal BOMs', async t => {
  for (const encoding of encodings) {
    const oracle = await loadOracle(t, path.join(assetDir, 'vendor', `${encoding}.js`));
    const target = '\uFEFF🍓🍓 日本語 e\u0301';
    const before = await oracle(target);
    assert.equal(oracle.decodeIds(before.ids), target);
    assert.ok(before.groups.some(g => g.ids.length > 1), 'at least one whole-character multi-token chip');
    const partial = (await oracle('🍓')).ids.slice(0, 1);
    assert.throws(() => oracle.decodeIds(partial), { code: 'ERR_ENCODING_INVALID_ENCODED_DATA' });
    await oracle('Ça coûte 3 € — où ?');
    assert.deepEqual(await oracle(target), before);
    assert.equal(oracle.decodeIds(before.ids), target);
  }
});

test('D1: pinned library streaming decoder hazard is reproduced outside the oracle', async () => {
  // This is the only deliberate library decode use in the suite. It proves
  // why neither expected chip pieces nor the page may use that shared stream.
  for (const encoding of encodings) {
    const context = vm.createContext({ TextEncoder, TextDecoder });
    vm.runInContext(await readAsset(`vendor/${encoding}.js`), context, { timeout: 10000 });
    const encoder = context[`GPTTokenizer_${encoding}`];
    const x = Array.from(encoder.encode('\uFEFF'));
    const clean = encoder.decode(x);
    encoder.decode([Array.from(encoder.encode('🍓'))[0]]);
    const poisoned = encoder.decode(x);
    assert.equal(clean, '', 'upstream streaming decoder consumes a leading BOM');
    assert.notEqual(poisoned, clean, 'pending UTF-8 bytes alter a later library decode');
    const safe = statelessDecoder(encoder);
    assert.equal(safe.decodeIds(x), '\uFEFF', 'raw-byte decoder preserves the BOM and ignores the shared stream');
  }
});

test('D1: renders are independent of typing, partial Unicode, toggles and preset history', async t => {
  const history = await pageFor(t);
  const fresh = await pageFor(t);
  const oracle = await oracles(t, history);
  const targets = ['\uFEFF', '\uFEFFabc', '🍓', '🍓🍓 日本語', 'Ça coûte 3 € — où ?',
    'é', 'e\u0301', '�', ' strawberry', 'hello world', ...generatedTexts().slice(0, 2)];
  const snapshot = page => page.evaluate(() => ['[data-tok-chips]', '[data-tok-ids]'].map(s => document.querySelector(s).innerHTML));
  for (const encoding of encodings) {
    for (const text of ['🍓', '\uD83C', '\uD83C\uDF53', '\uFEFF', 'ASCII right after emoji']) {
      await radio(history, encoding).check();
      await input(history).fill(text);
    }
    await input(history).fill('');
    // Slice by UTF-16 unit deliberately includes the lone-surrogate prefix
    // that appears while an emoji is being entered. Only valid target strings
    // must round-trip: UTF-8 encoders replace lone surrogates by U+FFFD.
    const mixed = '🍓🍓 日本語 — Ça coûte 3 € e\u0301';
    for (let end = 1; end <= mixed.length; end++) {
      await input(history).fill(mixed.slice(0, end));
      if (end % 4 === 0) await radio(history, encodings[(end / 4) % 2]).check();
    }
    await input(history).focus();
    await history.keyboard.insertText(' café\n12345678901234567890');
    await clickPresets(history, oracle, await presets(history));
    for (const text of targets) {
      // Exercise the partial-byte-to-ASCII regression immediately before each
      // target, rather than allowing intervening whole-byte decodes to flush it.
      await radio(history, encoding).check();
      await input(history).fill('🍓');
      await fill(history, oracle, encoding, text);
      await input(history).hover();
      await input(history).evaluate(n => n.blur());
      await fresh.goto(pathToFileURL(file).href);
      await fill(fresh, oracle, encoding, text);
      await input(fresh).hover();
      await input(fresh).evaluate(n => n.blur());
      assert.deepEqual(await snapshot(history), await snapshot(fresh), `${encoding} ${JSON.stringify(text)}: same DOM as a fresh document`);
    }
  }
});

test('D1: a multi-token Unicode chip links every ID with a visible ×n badge', async t => {
  const page = await pageFor(t);
  const oracle = await oracles(t, page);
  for (const encoding of encodings) {
    const expected = await fill(page, oracle, encoding, '🍓🍓 日本語 — où ?');
    const index = expected.groups.findIndex(g => g.ids.length > 1);
    assert.ok(index >= 0);
    const tokenIndex = expected.groups.slice(0, index).reduce((n, g) => n + g.ids.length, 0);
    const n = await chips(page).count();
    const members = Array.from({ length: expected.groups[index].ids.length }, (_, i) => tokenIndex + i);
    await input(page).hover();
    await input(page).evaluate(n => n.blur());
    for (const [direction, target] of [['chip', chips(page).nth(index)], ...members.map(i => [`id-${i}`, ids(page).nth(i)])]) {
      const before = await styles(page);
      await target.hover();
      const selectedId = direction === 'chip' ? null : Number(direction.slice(3));
      await activePair(page, index, selectedId);
      const after = await styles(page);
      assert.notDeepEqual(after[index], before[index], 'chip highlights');
      for (const i of selectedId === null ? members : [selectedId]) assert.notDeepEqual(after[n + i], before[n + i], 'each linked ID highlights');
      if (encoding === 'o200k_base') await screenshot(page, `tokenizer-grouped-hover-${direction}`);
      await input(page).hover();
      await activePair(page, null);
    }
    await chips(page).nth(index).focus();
    await activePair(page, index);
  }
});
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
  for (const encoding of encodings) {
    assert.equal(await radio(page, encoding).evaluate(n => !!n.closest('fieldset')), true);
    const label = normal(await radio(page, encoding).evaluate(n => [...n.labels].map(l => l.textContent).join(' ')));
    assert.match(label, new RegExp(encoding));
    assert.match(label, encoding === 'r50k_base' ? /GPT-?2/i : /GPT-?4o/i);
  }
  assert.equal(await page.evaluate(() => {
    const selectors = ['[data-predict]', 'textarea', '[data-tok-chips]', '[data-tok-ids]',
      'table[data-tok-compare]', '[data-tok-note]', '[data-tok-weight]'];
    const nodes = selectors.map(s => document.querySelector(s));
    return nodes.every(Boolean) && nodes.slice(1).every((n, i) =>
      !!(nodes[i].compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING));
  }), true, 'prediction, playground, comparison, note, then weight footer');
  const countLabel = await page.locator('output[data-tok-chars]').evaluate(n => [...n.labels].map(l => l.textContent).join(' ') || n.getAttribute('aria-label') || n.parentElement.textContent);
  assert.match(countLabel, /characters/i);
  assert.match(countLabel, /Unicode code points|code points/i, 'character unit is labelled');
  assert.equal(await radio(page, 'r50k_base').isChecked(), true, 'agreed default is GPT-2');
  const initial = await input(page).inputValue();
  assert.ok(initial.trim(), 'neutral initial sentence');
  assert.doesNotMatch(initial, /strawberry|\br['’]s\b|count.{0,15}\br\b/i);
  await rendered(page, initial, await oracle.r50k_base(initial));
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
  await fill(page, oracle, 'r50k_base', ' a\tb\nc');
  const whitespace = await chips(page).evaluateAll(nodes => nodes.map(n => [n, ...n.querySelectorAll('*')].map(el =>
    `${el.textContent} ${getComputedStyle(el, '::before').content} ${getComputedStyle(el, '::after').content}`).join(' ')).join(' '));
  for (const mark of ['␣', '→', '↵']) assert.ok(whitespace.includes(mark), `visible whitespace mark ${mark}`);
  await fill(page, oracle, 'o200k_base', 'One two three four five six seven eight nine.');
  const colors = await chips(page).evaluateAll(nodes => nodes.map(n => getComputedStyle(n).backgroundColor));
  assert.ok(colors.length > 2);
  for (let i = 1; i < colors.length; i++) assert.notEqual(colors[i], colors[i - 1], 'adjacent chips differ');
  assert.ok(await chips(page).evaluateAll(nodes => nodes.every(n => {
    const s = getComputedStyle(n);
    return ['Top', 'Right', 'Bottom', 'Left'].some(side => parseFloat(s[`border${side}Width`]) > 0 && s[`border${side}Style`] !== 'none');
  })), 'chips have a visible border as well as background tints');
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
    const disclosure = view.locator('details').filter({ has: view.locator('table[data-tok-compare]') });
    assert.equal(await disclosure.count(), 1, 'across-encodings table is in a disclosure');
    assert.equal(await disclosure.getAttribute('open'), null, 'comparison is closed initially');
    assert.match(await disclosure.locator('summary').textContent(), /Across encodings/i);
    await disclosure.locator('summary').click();
    const rows = view.locator('table[data-tok-compare] tr[data-tok-preset-row]');
    assert.equal(await view.locator('table[data-tok-compare]').isVisible(), true);
    const keys = await rows.evaluateAll(nodes => nodes.map(n => n.dataset.tokPresetRow));
    assert.equal(new Set(keys).size, keys.length, 'unique comparison rows');
    for (const required of ['strawberry', 'optimization', 'bonjour']) assert.ok(keys.includes(required), `comparison covers ${required}`);
    assert.ok(keys.every(key => values.some(p => p.key === key)), 'comparison rows correspond to actual presets');
    for (const p of values.filter(p => keys.includes(p.key))) {
      assert.equal(keys.filter(k => k === p.key).length, 1, `comparison row ${p.key}`);
      const actualRow = rows.nth(keys.indexOf(p.key));
      for (const encoding of encodings) {
        const cell = actualRow.locator(`td[data-encoding="${encoding}"]`);
        const expected = await oracle[encoding](p.value);
        assert.equal(integer(await cell.locator('[data-tok-compare-count]').textContent(), 'comparison count'), expected.ids.length);
        assert.deepEqual(idSequence(await cell.locator('[data-tok-compare-ids]').textContent()), expected.ids);
        if (['strawberry', 'optimization', 'bonjour'].includes(p.key)) {
          // Read authored piece boundaries from semantic text elements. A
          // full-word string containing every piece as a substring is not a
          // correct comparison of token pieces. No page-private function is used.
          const shownPieces = await cell.evaluate(n => {
            const marked = [...n.querySelectorAll('[data-text], [data-tok-compare-piece], code')];
            const candidates = marked.length ? marked : [...n.querySelectorAll('span')];
            return candidates.filter(el => !el.closest('[data-tok-compare-count], [data-tok-compare-ids]') &&
              !candidates.some(other => other !== el && el.contains(other)))
              .map(el => el.getAttribute('data-text') ?? el.textContent)
              .filter(text => text && !/^\s*[\d\s]+$/.test(text))
              .map(text => text.replaceAll('␣', ' '));
          });
          assert.deepEqual(shownPieces, expected.pieces, `${p.key}/${encoding}: every authored token piece`);
        }
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
  assert.match(await q1.locator('legend').textContent(), /tokens/i);
  assert.match(await q1.locator('legend').textContent(), /GPT-?2|r50k(?:_base)?/i);
  assert.match(await q2.locator('legend').textContent(), /\br(?:['’]s|s)?\b/i);
  for (const q of [q1, q2]) assert.equal(await q.locator('input[type=radio][data-correct]').count(), 1);
  const choiceLabels = q => q.locator('input[type=radio]').evaluateAll(nodes => nodes.map(n => [...n.labels].map(l => l.textContent).join(' ').trim()));
  assert.deepEqual((await choiceLabels(q1)).map(label => Number(label.match(/^\s*(\d+)/)?.[1])).sort((a, b) => a - b), [1, 2, 3, 11], 'token-count prediction choices');
  const rChoices = await choiceLabels(q2);
  for (const choice of [/^(?:3|three)\b/i, /^(?:2|two)\b/i, /^(?:1|one)\b/i, /IDs/i]) assert.ok(rChoices.some(label => choice.test(label)), 'letter prediction choices');
  const label = q => q.locator('input[data-correct]').evaluate(n => [...n.labels].map(l => l.textContent).join(' '));
  const r50k = await oracle.r50k_base(' strawberry');
  assert.match(await label(q1), new RegExp(`\\b${r50k.ids.length}\\b`));
  assert.match(await label(q2), /\b(?:0|zero|none)\b/i);
  assert.match(await label(q2), /\bIDs\b/);
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
  const prose = section(await readAsset('review.md'), /strawberry|prediction explanation/i);
  const quote = normal(prose.replace(/^\s*>\s?/gm, ''));
  for (const answer of await answers.allTextContents()) assert.ok(quote.includes(normal(answer)), 'review quotes the revealed explanation verbatim');
  // Semantic accuracy is assessed by the named prose review. Require a prose
  // judgement in addition to the quotation; keywords cannot prove its truth.
  const judgement = prose.split('\n').filter(line => !/^\s*>|^#/.test(line)).join(' ').trim();
  assert.ok(judgement.length >= 100, 'named strawberry prose review contains a judgement');
  const keyboard = await pageFor(t);
  const keyboardRoot = keyboard.locator('[data-predict]');
  for (const q of await keyboardRoot.locator('[data-predict-question]').all()) {
    await q.locator('input[data-correct]').focus();
    await keyboard.keyboard.press('Space');
  }
  await keyboardRoot.locator('[data-predict-lock]').focus();
  await keyboard.keyboard.press('Enter');
  for (const r of await keyboardRoot.locator('input[type=radio]').all()) assert.equal(await r.isDisabled(), true);
  assert.equal(await keyboardRoot.locator('[data-predict-reveal]').evaluate(n => document.activeElement === n), true);
  await keyboard.keyboard.press('Enter');
  for (const answer of await keyboardRoot.locator('[data-predict-answer]').all()) assert.equal(await answer.isVisible(), true);
  await screenshot(keyboard, 'tokenizer-predict-revealed');
  await keyboard.keyboard.press('Enter');
  await initialPredict(keyboardRoot);
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
    for (const phrase of [/not public/i, /OpenAI/i, /GPT-?2/i, /r50k_base/, /o200k_base/, /IDs/i]) assert.match(current, phrase);
    assert.match(current, /as of\s+\d{4}-\d{2}-\d{2}/i);
    assert.ok(await note.locator('a[href^="https://"]').count() > 0);
    assert.equal(await note.locator('a[href="https://platform.claude.com/docs/en/build-with-claude/token-counting"]').count(), 1);
  }
  const quote = section(await readAsset('review.md'), /Claude note/i).replace(/^\s*>\s?/gm, '');
  assert.ok(normal(quote).includes(text), 'verbatim note in review');
});

test('D5: independent npm trust anchors are a required authoring prerequisite', () => {
  // 2026-10-13: npm view gpt-tokenizer@3.4.0 dist.integrity dist.tarball
  // and npm pack gpt-tokenizer@3.4.0 --ignore-scripts were retried in a
  // fresh empty /tmp directory with fresh caches, --registry=https://registry.npmjs.org,
  // --fetch-retries=0 and --fetch-timeout=20000. Both failed with EAI_AGAIN
  // resolving registry.npmjs.org, so no tarball could be authenticated with
  // openssl dgst -sha512 -binary <tgz> | base64. The implementer's provenance/review
  // cannot serve as independent anchors. Do not replace this failure with
  // hashes computed from the implementation under test. A check-author pass
  // with registry access must retrieve the integrity and npm pack tarball,
  // authenticate it, then pin the three extracted file hashes here.
  assert.fail('Prerequisite failure: registry unreachable; independently authenticated gpt-tokenizer@3.4.0 integrity and extracted SHA-256 trust anchors could not be established.');
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
test('D5: two classic UMD encoders, known answers, license and provenance evidence', async t => {
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
    // Independently confirmed 2026-10-13 in OpenAI's upstream tests:
    // https://raw.githubusercontent.com/openai/tiktoken/main/tests/test_encoding.py
    // No o200k "hello world" answer appears there, so none is invented here.
    if (i === 0) assert.deepEqual((await oracle[encoding]('hello world')).ids, [31373, 995]);
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
    assert.ok(strings(value).some(s => s === `package/dist/${encoding}.js` || s === `dist/${encoding}.js`), 'source path in tarball');
    assert.ok(strings(value).some(s => s.endsWith(`vendor/${encoding}.js`)), 'vendored path');
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
  const licenseRecord = provenanceRecord(meta, 'LICENSE').value;
  assert.equal(licenseRecord.sha256, sha256(Buffer.from(license)));
  assert.ok(strings(licenseRecord).some(s => s === 'LICENSE' || s === 'package/LICENSE'), 'license package path');
  assert.ok(strings(licenseRecord).some(s => s.endsWith('vendor/LICENSE')), 'vendored license path');
  assert.ok(Object.entries(licenseRecord).some(([k, v]) => /bytes|size/i.test(k) && v === Buffer.byteLength(license)), 'license byte count');
  const readme = await readAsset('README.md');
  assert.match(readme, /3\.4\.0/);
  assert.match(readme, /(?:v(?:ersion\s*)?4|4\.0)[\s\S]{0,160}(?:UMD)|UMD[\s\S]{0,160}(?:v(?:ersion\s*)?4|4\.0)/i);
  assert.match(readme, /npm pack gpt-tokenizer@3\.4\.0/);
  // The agreed design keeps the re-vendoring recipe beside the lab; it does
  // not authorize changes to setup/README.md.
  assert.match(readme, /--ignore-scripts/);
  assert.match(readme, /tokenizer\/vendor/);
  assert.match(readme, /tryDecodeToken|rank.*(?:byte|decoder)|reset[ -]wrapped/i, 'recorded stateless byte-source path');
  const footer = page.locator('footer').filter({ has: page.locator('[data-tok-weight]') });
  assert.match(await footer.textContent(), /gpt-tokenizer[\s\S]*3\.4\.0/);
  assert.match(await footer.textContent(), /MIT/);
  const links = await footer.locator('a[href]').evaluateAll(nodes => nodes.map(n => n.getAttribute('href')));
  assert.ok(links.some(href => !/^(?:[a-z][\w+.-]*:|\/)/i.test(href) && fileURLToPath(new URL(href, pathToFileURL(file))) === path.join(assetDir, 'vendor/LICENSE')), 'relative vendored LICENSE credit');
  const live = await pageFor(t);
  for (const encoding of encodings) assert.equal(await live.evaluate(name => typeof window[name]?.encode, `GPTTokenizer_${encoding}`), 'function', 'expected UMD global on the real page');
  const values = await presets(live);
  for (const p of values) for (const encoding of encodings) {
    const expected = await oracle[encoding](p.value);
    assert.equal(oracle[encoding].decodeIds(expected.ids), p.value, `${p.key} round-trips`);
  }
  const french = values.find(p => p.key === 'french').value;
  assert.ok((await oracle.o200k_base(french)).ids.some(id => id > 50256), 'French preset exercises o200k IDs beyond GPT-2 vocabulary');
});

function forbidNetworkAPIs() {
  window.__networkCalls = [];
  const reject = label => function () {
    window.__networkCalls.push(label);
    throw new Error(`Offline lab called ${label}`);
  };
  window.fetch = reject('fetch');
  XMLHttpRequest.prototype.open = reject('XMLHttpRequest');
  navigator.sendBeacon = reject('sendBeacon');
  for (const name of ['WebSocket', 'Worker', 'SharedWorker', 'EventSource']) {
    if (name in window) window[name] = reject(name);
  }
}

test('A1: isolated file copy uses no network APIs while all controls work offline', async t => {
  await readRequired(file);
  const dir = await scratch(t), copy = path.join(dir, 'tokenizer.html');
  await cp(file, copy);
  await cp(assetDir, path.join(dir, 'tokenizer'), { recursive: true });
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const context = await browser.newContext({ offline: true, serviceWorkers: 'block' });
  const remote = [], requests = [], errors = [];
  await context.route(/^(?:https?|wss?):/i, route => { remote.push(route.request().url()); return route.abort(); });
  await context.addInitScript(forbidNetworkAPIs);
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  page.on('request', request => requests.push(request.url()));
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(pathToFileURL(copy).href);
  const oracle = await oracles(t, page);
  await clickPresets(page, oracle, await presets(page));
  for (const encoding of encodings) for (const text of examples()) await fill(page, oracle, encoding, text);
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
    prose: 'Bonjour, où sont les contraintes du modèle ? Un café près de la rivière. A small bird follows the quiet path. 🍓🍓 日本語 12345678901234567890 ',
    code: 'def objective(x):\n    return sum(c * v for c, v in zip(costs, x))\n\\sum_{j=1}^{n} a_{ij} x_j \\le b_i\n',
    numbers: '12345678901234567890 9876543210,.;:!? +-*/=()[]{} 0.000123 42% #7 | 555_012_345\n',
    unbroken: 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
  };
  return Object.entries(seeds).map(([name, seed]) => [name, [...seed.repeat(Math.ceil(2000 / [...seed].length))].slice(0, 2000).join('')]);
}
test('A1: first input, encoding switch and twenty keystrokes all finish below 50 ms', async t => {
  await readRequired(file);
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const context = await browser.newContext({ offline: true, serviceWorkers: 'block', viewport: { width: 1440, height: 900 } });
  const errors = [];
  await context.route(/^(?:https?|wss?):/i, route => { errors.push(route.request().url()); return route.abort(); });
  await context.addInitScript(forbidNetworkAPIs);
  await context.addInitScript(() => {
    window.__samples = [];
    window.__expected = null;
    let start;
    const relevant = event => window.__expected && (event.type === 'input' && event.target.matches('textarea') ||
      event.type === 'change' && event.target.matches('input[name=encoding]'));
    const begin = event => { if (relevant(event)) start = performance.now(); };
    const finish = event => {
      if (!relevant(event)) return;
      const expected = window.__expected, began = start;
      const observe = () => {
        const matches = selector => {
          const nodes = [...document.querySelectorAll(selector)];
          return nodes.length === expected.ids.length && nodes.every((n, i) => n.getAttribute('data-token-id') === String(expected.ids[i]) && n.textContent.trim() === String(expected.ids[i]));
        };
        const count = document.querySelector('[data-tok-count]')?.textContent.trim();
        const renderedIds = [...document.querySelectorAll(':is([data-tok-chip], [data-chip]):not(table *)')].flatMap(n =>
          (n.getAttribute('data-token-ids') ?? n.getAttribute('data-ids') ?? '').trim().split(/\s+/).filter(Boolean).map(Number));
        const renderedText = [...document.querySelectorAll(':is([data-tok-chip], [data-chip]):not(table *)')].map(n => n.getAttribute('data-text') ?? '').join('');
        const chars = document.querySelector('[data-tok-chars]')?.textContent.trim();
        if (renderedIds.length === expected.ids.length && renderedIds.every((id, i) => id === expected.ids[i]) &&
          renderedText === expected.text && matches(':is([data-tok-id], [data-id-of]):not(table *)') && count === String(expected.ids.length) && chars === String(expected.chars)) {
          void document.body.offsetHeight;
          window.__samples.push(performance.now() - began);
        } else if (performance.now() - began >= 1000) window.__samples.push({ timeout: true });
        else requestAnimationFrame(observe);
      };
      observe(); // Stop only after the correct DOM and a forced layout exist.
    };
    for (const type of ['input', 'change']) {
      window.addEventListener(type, begin, true);
      window.addEventListener(type, finish);
    }
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(pathToFileURL(file).href);
  const oracle = await oracles(t, page);
  t.diagnostic(`CPU: ${cpus()[0]?.model ?? 'unknown'}; OS: ${platform()} ${release()}; browser: ${browser.version()}; no CPU throttling`);
  const all = [];
  for (const [name, corpus] of corpora()) for (const firstEncoding of encodings) {
    assert.equal([...corpus].length, 2000);
    await page.goto(pathToFileURL(file).href); // Fresh context state, no timed update discarded.
    await radio(page, firstEncoding).check();
    const prepare = async (encoding, text) => {
      const expected = await oracle[encoding](text);
      await page.evaluate(expected => { window.__expected = expected; }, { ids: expected.ids, chars: [...text].length, text });
    };
    await prepare(firstEncoding, corpus);
    await input(page).evaluate((n, v) => { n.value = v; n.dispatchEvent(new Event('input', { bubbles: true })); }, corpus);
    await page.waitForFunction(() => window.__samples.length === 1, null, { timeout: 3000 });
    await rendered(page, corpus, await oracle[firstEncoding](corpus));
    const encoding = encodings.find(e => e !== firstEncoding);
    await prepare(encoding, corpus);
    await radio(page, encoding).check();
    await page.waitForFunction(() => window.__samples.length === 2, null, { timeout: 3000 });
    await rendered(page, corpus, await oracle[encoding](corpus));
    await input(page).focus();
    await input(page).evaluate(n => n.setSelectionRange(n.value.length, n.value.length));
    let text = corpus;
    for (let i = 0; i < 20; i++) {
      const char = ['a', 'é', '7', ' ', '🍓'][i % 5];
      text += char;
      await prepare(encoding, text);
      await page.keyboard.type(char);
      await page.waitForFunction(n => window.__samples.length === n, i + 3, { timeout: 3000 });
    }
    const samples = await page.evaluate(() => window.__samples);
    all.push(...samples);
    const numeric = samples.filter(Number.isFinite).sort((a, b) => a - b);
    const median = numeric.length === 22 ? (numeric[10] + numeric[11]) / 2 : null;
    t.diagnostic(JSON.stringify({ corpus: name, firstEncoding, encoding, n: samples.length, first_input_ms: samples[0], switch_ms: samples[1], samples, median_ms: median, max_ms: numeric.length ? Math.max(...numeric) : null }));
    assert.equal(samples.length, 22, 'first input, first encoding switch and twenty real keystrokes');
    assert.deepEqual(await page.evaluate(() => window.__networkCalls), []);
    await rendered(page, text, await oracle[encoding](text));
  }
  assert.deepEqual(errors, []);
  assert.equal(all.length, corpora().length * encodings.length * 22, 'no warm-up exclusion, retries or discarded samples');
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
  assert.match(weight, /\bMiB\b/);
  assert.match(weight, /(?:about|~|estimate)[\s\S]{0,80}2\.5\s*MB|2\.5\s*MB[\s\S]{0,100}(?:estimate|measured)/i, 'comparison to the issue estimate');
  for (const value of [subtotal, total]) {
    const row = lines.find(line => contains(line, value));
    const decimals = [...row.matchAll(/\b(\d+)\.(\d+)\b/g)];
    assert.ok(decimals.some(m => Math.abs(Number(m[0]) - value / 1e6) <= 0.5 * 10 ** -m[2].length + 1e-10), 'decimal MB value for subtotal and total');
  }
  const totalRow = lines.find(line => /total/i.test(line) && contains(line, total));
  const mib = totalRow.match(/(\d+(?:\.\d+)?)\s*MiB/i);
  assert.ok(mib, 'full total in MiB');
  assert.ok(Math.abs(Number(mib[1]) - total / 2 ** 20) < 0.01, 'true binary MiB');
  const review = (await readAsset('review.md')).replace(/(?<=\d)[,_\u202f](?=\d)/g, '');
  assert.ok(review.split('\n').some(line => line.includes('tokenizer.html') && contains(line, sizes[0])), 'review records exact final HTML byte count');
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
  section(review, /strawberry|prediction explanation/i);
  assert.ok(review.includes(`node tools/html-pages/check-page.mjs ${relative}.html --output artifacts/html-pages/tokenizer`), 'exact check-page command and output directory');
  assert.match(review, /\bPASS\b/, 'documented checker PASS result');
  const shots = section(review, /screenshots/i);
  for (const label of [/desktop/i, /laptop/i, /mobile/i, /no[- ](?:JS|JavaScript)|without JavaScript/i,
    /print/i, /reduced[- ]motion/i, /r50k/i, /o200k/i, /hover/i, /reveal/i,
    /2[,. ]?000[- ]character/i, /whitespace/i, /wrap/i, /overflow/i, /emoji|🍓/,
    /multi[- ]token|split characters|grouped/i, /hover.{0,60}chip|chip.{0,60}hover/i,
    /hover.{0,60}ID|ID.{0,60}hover/i]) assert.match(shots, label);
  for (const view of [/desktop/i, /laptop/i, /mobile/i, /no[- ](?:JS|JavaScript)/i, /print/i, /reduced[- ]motion/i]) {
    assert.ok(shots.split('\n').some(line => view.test(line) && line.replace(/\*|`/g, '').trim().length > 35), `concrete observation for ${view}`);
  }
});
