import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../../../../tools/html-pages/browser.mjs';
import { repoRoot, eventually } from '../../../../tools/html-pages/tests/component-helpers.mjs';

/* The next-token lab: its sampling math (checked against an independent oracle, never against
 * NextToken itself), the guess-then-reveal flow over the recorded fixture, the class tally and the
 * sampler. Controls are found by their accessible names. Layout, accessibility and the no-JS view
 * are the page checker's.
 */
const base = 'sessions/01-fundamentals/cursus';
const file = path.join(repoRoot, base, 'labs/next-token.html');
const fixtureText = await readFile(path.join(repoRoot, base, 'fixtures/next_token.json'), 'utf8');
const fixture = JSON.parse(fixtureText);
const prompts = fixture.prompts;
const KEY = 'cursus-s1-next-token-tally-v1';
const normal = s => s.replace(/\s+/g, ' ').trim();
const display = s => s.replace(/^ /, '␣').replace(/\n/g, '↵');
const sum = xs => xs.reduce((a, b) => a + b, 0);
const guessInput = page => page.getByRole('textbox', { name: /guess|bet/i });
const lock = page => page.getByRole('button', { name: /lock/i });
const reveal = page => page.getByRole('button', { name: /reveal/i });
const next = page => page.getByRole('button', { name: /next/i });
const previous = page => page.getByRole('button', { name: /prev|back/i });
const batch = page => page.getByRole('button', { name: /sample\s*[×x]\s*100/i });
const slider = (page, name) => page.getByRole('slider', { name });
const ranges = [ /temperature/i, /top[ -]*k/i, /top[ -]*p/i ];
const totalLabel = /total\s*(?:locked\s*)?(?:guesses|bets)|(?:guesses|bets)\s*total/;

function close(actual, expected, tolerance = 1e-9, label = 'value') {
  assert.ok(Number.isFinite(actual), `${label}: finite, received ${actual}`);
  assert.ok(Math.abs(actual - expected) <= tolerance, `${label}: ${actual} != ${expected} ± ${tolerance}`);
}
function vector(actual, expected, tolerance = 1e-9) {
  assert.equal(actual.length, expected.length, 'vector length');
  actual.forEach((v, i) => close(v, expected[i], tolerance, `index ${i}`));
}
// Independent numerical oracle; never delegates expected answers to NextToken.
function softmax(logits, temperature) {
  const largest = Math.max(...logits);
  const weights = logits.map(x => Math.exp((x - largest) / temperature));
  return weights.map(x => x / sum(weights));
}
function prefix(probabilities, threshold, candidates = probabilities.map((_, i) => i)) {
  const order = [...candidates].sort((a, b) => probabilities[b] - probabilities[a] || a - b);
  if (threshold === 1) return order;
  let mass = 0;
  const keep = [];
  for (const i of order) {
    keep.push(i);
    mass += probabilities[i];
    if (mass >= threshold) break;
  }
  return keep;
}
function distribution(logits, { temperature, topK, topP }) {
  const p = softmax(logits, temperature);
  const k = prefix(p, 1).slice(0, topK);
  const kMass = sum(k.map(i => p[i]));
  const afterK = p.map((x, i) => k.includes(i) ? x / kMass : 0);
  const kept = prefix(afterK, topP, k);
  const mass = sum(kept.map(i => p[i]));
  return { p, kept, q: p.map((x, i) => kept.includes(i) ? x / mass : 0), mass };
}
function inverseCDF(q, u) {
  let mass = 0;
  for (let i = 0; i < q.length; i++) {
    mass += q[i];
    if (u < mass) return i;
  }
  return q.findLastIndex(x => x > 0);
}

let browser;
before(async () => { browser = await chromium.launch(); });
after(() => browser?.close());

// A fresh context per test (its own localStorage) in the one browser.
async function pageFor(t, { init } = {}) {
  const context = await browser.newContext({ offline: true, viewport: { width: 1280, height: 900 } });
  t.after(() => context.close());
  if (init) await context.addInitScript(init);
  await context.route(/^(?:https?|wss?):/i, route => route.abort());
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  t.after(() => assert.deepEqual(errors, [], 'no page errors'));
  await page.goto(pathToFileURL(file).href);
  return page;
}
async function api(page, method, args) {
  return page.evaluate(({ method, args }) => {
    const result = window.NextToken[method](...args);
    if (Array.isArray(result) || ArrayBuffer.isView(result)) return Array.from(result);
    return { ...result, p: Array.from(result.p), kept: Array.from(result.kept), q: Array.from(result.q) };
  }, { method, args });
}
async function visit(page, index, current = 0) {
  if (index !== current) {
    // Travel through the button's own handler (a real click costs ~40 ms), then click it for real.
    const move = index > current ? next(page) : previous(page);
    await move.evaluate((button, n) => { for (let i = 0; i < n; i++) button.click(); }, Math.abs(index - current) - 1);
    await move.click();
  }
  const text = normal(await page.locator('body').innerText());
  assert.match(text, new RegExp(`Prompt\\s+${index + 1}\\s+of\\s+${prompts.length}\\b`, 'i'));
  assert.ok(text.includes(normal(prompts[index].prompt)), 'visible fixture prompt');
}
async function lockedGuess(page, value) {
  await guessInput(page).fill(value);
  await lock(page).click();
  assert.equal(await reveal(page).isEnabled(), true);
}
async function revealPrompt(page, index = 0, current = 0) {
  await visit(page, index, current);
  await lockedGuess(page, display(prompts[index].top[0].text));
  await reveal(page).click();
  assert.equal(await guessInput(page).isEnabled(), false);
}
async function values(chart) {
  return chart.locator('li[data-value]').evaluateAll(nodes => nodes.map(n => Number(n.dataset.value)));
}
async function charts(page, prompt) {
  const all = page.locator('ol[data-prob-chart]');
  assert.equal(await all.count(), 3, 'recorded probabilities, sandbox, histogram');
  let recorded, sampling, histogram;
  for (const chart of await all.all()) {
    if (await chart.locator('[data-nucleus]').count()) sampling = chart;
    else if ((await values(chart)).some(x => x > 0)) recorded = chart;
    else histogram = chart;
  }
  assert.ok(recorded && sampling && histogram, 'distinct revealed, sampling and initially empty histogram charts');
  assert.ok((await values(recorded)).length >= prompt.top.length);
  return { recorded, sampling, histogram };
}
// Nothing about the probabilities shows before a guess is locked and revealed.
async function concealed(page) {
  assert.equal(await reveal(page).isEnabled(), false, 'Reveal requires a locked guess');
  for (const chart of await page.locator('ol[data-prob-chart]').all()) assert.equal(await chart.isVisible(), false);
  for (const name of ranges) assert.equal(await slider(page, name).count(), 0, 'sampling sliders hidden');
}
async function setRange(page, name, value) {
  const input = slider(page, name);
  const { min, max, step } = await input.evaluate(el => ({ min: Number(el.min), max: Number(el.max), step: Number(el.step || 1) }));
  const low = Math.round((value - min) / step), high = Math.round((max - value) / step);
  await input.focus();
  await input.press(low <= high ? 'Home' : 'End');
  for (let i = 0; i < Math.min(low, high); i++) await input.press(low <= high ? 'ArrowRight' : 'ArrowLeft');
  close(Number(await input.inputValue()), value, 1e-8, 'keyboard slider value');
}
async function settings(page, opts) {
  await setRange(page, ranges[0], opts.temperature);
  await setRange(page, ranges[1], opts.topK);
  await setRange(page, ranges[2], opts.topP);
}
async function chartMatches(chart, prompt, expected, nucleus = null) {
  const rows = await chart.locator('li[data-value]').evaluateAll(nodes => nodes.map(n => ({
    label: n.querySelector('[data-prob-label]')?.innerText ?? '', kept: n.hasAttribute('data-nucleus'), text: n.innerText,
  })));
  assert.equal(rows.length, prompt.top.length);
  vector(await values(chart), expected);
  rows.forEach((row, i) => {
    assert.ok(row.label.includes(display(prompt.top[i].text)), `token ${i} with whitespace markers`);
    if (nucleus) {
      assert.equal(row.kept, nucleus.includes(i), `token ${i} in the nucleus`);
      assert.match(row.text, nucleus.includes(i) ? /\bkept\b/i : /\bcut\b/i);
    }
  });
}
// After Reveal, each locked guess shows its rank(s), or that it is not in the top 20.
const feedback = page => page.getByRole('list', { name: /locked guesses/i }).innerText();
function ranksIn(text) {
  return [...text.matchAll(/\brank\s*#?\s*(\d+)|#(\d+)/gi)].map(m => Number(m[1] ?? m[2]));
}

function findKey(tree, key) {
  if (!tree || typeof tree !== 'object') return undefined;
  if (Object.hasOwn(tree, key)) return tree[key];
  for (const value of Object.values(tree)) {
    const found = findKey(value, key);
    if (found !== undefined) return found;
  }
}
function storedCount(value) {
  if (typeof value === 'number') return value;
  if (Array.isArray(value)) return value.length;
  if (value && typeof value === 'object') {
    for (const [key, count] of Object.entries(value)) {
      if (/count|total|votes|guesses/i.test(key) && typeof count === 'number') return count;
    }
  }
  assert.fail(`expected a persisted count, got ${JSON.stringify(value)}`);
}
const tally = page => page.evaluate(key => JSON.parse(localStorage.getItem(key)), KEY);
const tallyText = page => page.getByRole('region', { name: /class tally/i }).innerText();
function metric(text, label, expected) {
  const pattern = new RegExp(`(?:${label.source})[^\\d\\n]{0,30}(\\d+)|(\\d+)[^\\d\\n]{0,20}(?:${label.source})`, 'i');
  const match = text.match(pattern);
  assert.ok(match, `visible tally metric ${label}: ${text}`);
  assert.equal(Number(match[1] ?? match[2]), expected, `tally metric ${label}`);
}

async function histogramMatches(chart, prompt, counts) {
  const rows = chart.locator('li[data-value]');
  await chartMatches(chart, prompt, counts.map(n => n / 100));
  for (let i = 0; i < counts.length; i++) {
    const text = await rows.nth(i).innerText();
    // Percentages alone do not communicate that these are observed counts.
    const withoutPercentages = text.replace(/\d+(?:\.\d+)?\s*%/g, '');
    assert.match(withoutPercentages, new RegExp(`(?:^|\\D)${counts[i]}(?:\\D|$)`), 'histogram count text');
  }
}
async function histogramEmpty(chart) {
  const current = await values(chart);
  assert.ok(current.length === 0 || current.every(value => value === 0), 'old histogram cleared');
}

test('the page embeds the recorded fixture verbatim and names its model revision', async () => {
  const html = await readFile(file, 'utf8');
  const block = html.match(/<script type="application\/json" id="next-token-data"[^>]*>([\s\S]*?)<\/script>/);
  assert.ok(block, 'inline fixture');
  assert.deepEqual(JSON.parse(block[1]), fixture);
  const footer = html.match(/<footer\b[\s\S]*?<\/footer>/)?.[0] ?? '';
  for (const model of fixture.meta.models) assert.ok(footer.includes(model.id) && footer.includes(model.revision), `provenance ${model.id}`);
  assert.ok(footer.includes(fixture.meta.date), 'generation date');
});

test('sampling math: tempered softmax, top-p crossing and ties, top-k before the nucleus, one draw per sample, argmax', async t => {
  const page = await pageFor(t);
  const z = [-3.75, 2.125, 0.33, 8.1, 8.09, -19];
  for (const T of [0.1, 1, 17]) {
    const got = await api(page, 'softmax', [z, T]);
    vector(got, softmax(z, T));
    vector(await api(page, 'softmax', [z.map(x => x + 1234), T]), got, 1e-11);
  }
  const extreme = await api(page, 'softmax', [[1000, -1000, 0], 1]);
  assert.ok(extreme.every(Number.isFinite)); close(sum(extreme), 1);
  vector(await api(page, 'softmax', [[3, 1, -1], 0.001]), [1, 0, 0]);
  const pure = await page.evaluate(() => {
    const z = [0.3, 8, -5, 8], before = [...z];
    NextToken.softmax(z, 0.7);
    return { before, after: z, rejected: [0, -1, NaN].map(T => { try { NextToken.softmax([2, 1], T); return false; } catch { return true; } }) };
  });
  assert.deepEqual(pure.after, pure.before, 'softmax leaves its input alone');
  assert.deepEqual(pure.rejected, [true, true, true], 'invalid temperatures throw');
  for (const [p, threshold, expected] of [
    [[0.25, 0.25, 0.25, 0.25], 0.5, [0, 1]],
    [[0.25, 0.25, 0.25, 0.25], 0.500001, [0, 1, 2]],
    [[0.1, 0.4, 0.2, 0.3], 0.65, [1, 3]],
    [[0.3, 0.1, 0.3, 0.3], 0.6, [0, 2]],
    [[0.5, 0.5, 0, 0], 1, [0, 1, 2, 3]],
  ]) assert.deepEqual(await api(page, 'topP', [p, threshold]), expected);
  for (const zs of [[0, 3, 2, 1], [2.4, -8, 1, 2.4, 0.2]]) {
    for (const opts of [{ temperature: 1, topK: 2, topP: 0.7 }, { temperature: 2, topK: zs.length, topP: 0.55 }, { temperature: 0.1, topK: 1, topP: 1 }]) {
      const want = distribution(zs, opts), got = await api(page, 'distribution', [zs, opts]);
      vector(got.p, want.p); vector(got.q, want.q); assert.deepEqual(got.kept, want.kept);
    }
  }
  const q = [0, 0.125, 0.375, 0, 0.5, 0];
  for (const u of [0, 0.124999, 0.125, 0.5, 0.999999]) {
    const result = await page.evaluate(({ q, u }) => {
      let calls = 0;
      const selected = NextToken.sample(q, () => { calls++; return u; });
      return { selected, calls };
    }, { q, u });
    assert.equal(result.calls, 1); assert.equal(result.selected, inverseCDF(q, u));
  }
  assert.equal(await page.evaluate(() => NextToken.argmax([0.1, 0.2, 0.7])), 2);
});

test('a prompt hides its probabilities until a guess is locked and revealed, then charts the recorded distribution; the carousel goes both ways', async t => {
  const page = await pageFor(t);
  let current = 0;
  for (const index of [0, prompts.findIndex(p => p.id === 'code-return')]) {
    await visit(page, index, current);
    current = index;
    await concealed(page);
    const prompt = prompts[index];
    await lockedGuess(page, display(prompt.top[0].text));
    for (const chart of await page.locator('ol[data-prob-chart]').all()) assert.equal(await chart.isVisible(), false, 'locking alone reveals nothing');
    await reveal(page).click();
    assert.equal(await guessInput(page).isEnabled(), false);
    const { recorded } = await charts(page, prompt);
    const want = prompt.top.map(token => Math.exp(token.logit - prompt.logsumexp));
    vector((await values(recorded)).slice(0, prompt.top.length), want, 1e-6);
    const labels = await recorded.locator('[data-prob-label]').allInnerTexts();
    prompt.top.forEach((token, i) => assert.ok(labels[i].includes(display(token.text)), `token ${i}`));
    // The rest of the full vocabulary is accounted for.
    const others = page.getByText(/(?:all\s+)?other tokens/i).filter({ visible: true });
    const otherMass = await others.first().evaluate(el => {
      const row = el.closest('[data-value]');
      return row ? { exact: Number(row.dataset.value) } : { text: /\d/.test(el.innerText) ? el.innerText : el.parentElement.innerText };
    });
    if ('exact' in otherMass) close(otherMass.exact, 1 - sum(want), 1e-6);
    else assert.ok([...otherMass.text.matchAll(/(\d+(?:\.\d+)?)\s*%/g)].some(m => Math.abs(Number(m[1]) / 100 - (1 - sum(want))) <= 0.0051), 'other-token mass');
  }
  await visit(page, prompts.length - 1, current);
  await concealed(page);
  await visit(page, 0, prompts.length - 1);
  await concealed(page);
});

test('guesses match exact whitespace, report every rank of an ambiguous guess, accept newline notation, and report misses', async t => {
  const page = await pageFor(t);
  const index = prompts.findIndex(p => p.id === 'idiom-thanks'), prompt = prompts[index];
  const exactRank = prompt.top.findIndex(token => token.text === 'much') + 1;
  const spacedRank = prompt.top.findIndex(token => token.text === ' much') + 1;
  assert.ok(index >= 0 && exactRank > 0 && spacedRank > 0, 'fixture witness');
  const newlineIndex = prompts.findIndex(p => p.top.some(token => token.text === '\n'));
  const newlineRank = prompts[newlineIndex].top.findIndex(token => token.text === '\n') + 1;
  const cases = [
    { index, guess: 'much', ranks: [exactRank] },
    { index, guess: '␣much', ranks: [spacedRank] },
    { index, guess: '  much  ', ranks: [spacedRank, exactRank], ambiguous: true },
    { index: newlineIndex, guess: '↵', ranks: [newlineRank] },
    { index: newlineIndex, guess: '\\n', ranks: [newlineRank] },
    { index: 0, guess: 'zz_unlisted_class_bet_7391', ranks: [] },
  ];
  for (const item of cases) {
    await page.reload();
    await visit(page, item.index);
    await lockedGuess(page, item.guess);
    await reveal(page).click();
    const result = await feedback(page);
    if (!item.ranks.length) assert.match(result, /not in (?:the )?top\s*20/i);
    else assert.deepEqual([...new Set(ranksIn(result))].sort((a, b) => a - b), [...item.ranks].sort((a, b) => a - b),
      `rank feedback for ${JSON.stringify(item.guess)}: ${result}`);
    if (item.ambiguous) for (const rank of item.ranks) assert.ok(result.includes(display(prompt.top[rank - 1].text)), 'names both tokens');
  }
});

test('the tally counts locks by token id and misses by text, survives a reload and resets', async t => {
  const page = await pageFor(t);
  const prompt = prompts[0], miss = 'unlisted raw miss 7391';
  for (const raw of [display(prompt.top[0].text), display(prompt.top[0].text), display(prompt.top[6].text), miss]) {
    await lockedGuess(page, raw);
  }
  const state = await tally(page), record = findKey(state, prompt.id);
  assert.ok(record, 'prompt-id tally bucket');
  assert.equal(storedCount(findKey(record, String(prompt.top[0].id))), 2);
  assert.equal(storedCount(findKey(record, String(prompt.top[6].id))), 1);
  assert.equal(storedCount(findKey(findKey(record, 'miss'), miss)), 1, 'raw guess text keys the miss');
  await reveal(page).click();
  const summary = await tallyText(page);
  metric(summary, totalLabel, 4);
  metric(summary, /(?:hits?\s*(?:at\s*)?)?rank\s*1|top\s*1/, 2);
  metric(summary, /(?:hits?\s*(?:in\s*)?(?:the\s*)?)?top\s*5/, 2);
  await page.reload();
  assert.deepEqual(await tally(page), state, 'reload retains tally without double counting');
  await next(page).click();
  await lockedGuess(page, display(prompts[1].top[1].text));
  const second = await tally(page);
  assert.deepEqual(findKey(second, prompt.id), record, 'separate prompt buckets');
  assert.equal(storedCount(findKey(findKey(second, prompts[1].id), String(prompts[1].top[1].id))), 1);
  await page.getByRole('button', { name: /reset tally/i }).click();
  await page.reload();
  metric(await tallyText(page), totalLabel, 0);
});

test('a corrupt or unavailable localStorage still gives a working tally', async t => {
  const corrupt = await pageFor(t, { init: () => localStorage.setItem('cursus-s1-next-token-tally-v1', '{broken json') });
  await lockedGuess(corrupt, display(prompts[0].top[0].text));
  assert.equal(storedCount(findKey(findKey(await tally(corrupt), prompts[0].id), String(prompts[0].top[0].id))), 1);
  const unavailable = await pageFor(t, { init: () => {
    Object.defineProperty(window, 'localStorage', { configurable: true, get() { throw new Error('storage unavailable'); } });
  } });
  await lockedGuess(unavailable, display(prompts[0].top[0].text));
  await reveal(unavailable).click();
  metric(await tallyText(unavailable), totalLabel, 1);
  await unavailable.getByRole('button', { name: /reset tally/i }).click();
  metric(await tallyText(unavailable), totalLabel, 0);
});

test('the sliders recompute q, the labelled nucleus, its size and the mass it keeps', async t => {
  const page = await pageFor(t);
  const index = prompts.findIndex(p => p.id === 'code-return'), prompt = prompts[index], n = prompt.top.length;
  await revealPrompt(page, index);
  const { sampling } = await charts(page, prompt);
  assert.equal(await slider(page, ranges[1]).getAttribute('max'), String(n), 'top-k reaches the whole list');
  for (const opts of [
    { temperature: 0.1, topK: 1, topP: 0.05 },
    { temperature: 0.65, topK: 7, topP: 0.75 },
    { temperature: 1.85, topK: 3, topP: 0.55 },
  ]) {
    await settings(page, opts);
    const expected = distribution(prompt.top.map(token => token.logit), opts);
    await eventually(() => chartMatches(sampling, prompt, expected.q, expected.kept));
    const body = await page.locator('body').innerText();
    assert.match(body, new RegExp(`(?:kept|keep|nucleus)[^\\n\\d]{0,25}${expected.kept.length}\\b|\\b${expected.kept.length}[^\\n\\d]{0,25}(?:kept|retained|candidates)`, 'i'));
    assert.ok([...body.matchAll(/(\d+(?:\.\d+)?)\s*%/g)].some(m => Math.abs(Number(m[1]) / 100 - expected.mass) <= 0.0051), 'pre-filter retained mass is shown');
  }
});

test('a seeded batch gives exact counts; argmax uses no randomness; a slider or prompt change clears the histogram', async t => {
  const page = await pageFor(t, { init: () => {
    window.__nextTokenTestDraws = 0;
    Math.random = () => ((window.__nextTokenTestDraws++ % 100) + 0.5) / 100;
  } });
  await revealPrompt(page);
  const prompt = prompts[0], { sampling, histogram } = await charts(page, prompt);
  const opts = { temperature: 2, topK: 9, topP: 0.85 };
  await settings(page, opts);
  const want = distribution(prompt.top.map(token => token.logit), opts);
  assert.ok(want.kept.length >= 2, 'nontrivial sampling witness');
  await chartMatches(sampling, prompt, want.q, want.kept);
  await page.getByRole('radio', { name: /^sample$/i }).check();
  const expectedCounts = Array(prompt.top.length).fill(0);
  for (let i = 0; i < 100; i++) expectedCounts[inverseCDF(want.q, (i + 0.5) / 100)]++;
  const draws = () => page.evaluate(() => window.__nextTokenTestDraws);
  const before = await draws();
  await batch(page).click();
  assert.equal(await draws(), before + 100);
  await eventually(() => histogramMatches(histogram, prompt, expectedCounts));
  await page.getByRole('radio', { name: /argmax/i }).check();
  const greedyBefore = await draws();
  await batch(page).click();
  const greedy = Array(prompt.top.length).fill(0);
  greedy[want.q.indexOf(Math.max(...want.q))] = 100;
  await histogramMatches(histogram, prompt, greedy);
  assert.equal(await draws(), greedyBefore, 'Argmax consumes no randomness');
  await setRange(page, ranges[0], 1.5);
  await histogramEmpty(histogram);
  await batch(page).click();
  close(sum(await values(histogram)), 1);
  await next(page).click();
  await concealed(page);
  await histogramEmpty(histogram);
});
