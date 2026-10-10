import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { cpus, platform, release } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { repoRoot, suites, scratch, openPage, eventually } from './component-helpers.mjs';

/* Issue 29's agreed public surface, with the otherwise unspecified sampling
 * call convention made explicit:
 *   distribution(logits, temperature, topP) -> { p, order, nucleus, q }
 *   sample(distribution, rngFunction) -> integer token id
 *   mulberry32(uint32Seed) -> function returning a number in [0, 1).
 * p and q are indexed by token id; order and nucleus contain ids. Arrays and
 * typed arrays are both supported. encode(prompt) includes BOS.
 * No UI control ids or application-private functions are assumed. Controls
 * have accessible names containing Prompt, Seed, Temperature, Top-p, Step,
 * Run, Reset (formula reset buttons are excluded from the generation reset).
 * Provenance object nesting and review heading wording are not prescribed.
 * Tests never download assets, rewrite review evidence, or skip prerequisites.
 */
const relative = 'sessions/01-fundamentals/cursus/labs/tiny-lm';
const file = path.join(repoRoot, `${relative}.html`);
const assetDir = path.join(repoRoot, relative);
const readAsset = name => readFile(path.join(assetDir, name), 'utf8');
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const normal = text => text.replace(/\s+/g, ' ').trim();
const chips = page => page.locator('button[data-tlm-token][data-pos][data-id]');
const promptControl = page => page.getByRole('textbox', { name: /prompt/i });
const seedControl = page => page.getByLabel(/seed/i);
const stepControl = page => page.getByRole('button', { name: /^step\b/i });
const runControl = page => page.getByRole('button', { name: /^run\b/i });
const resetControl = page => page.getByRole('button', { name: /^reset\b/i }).and(page.locator('button:not([data-formula-reset])'));
const temperatureControl = page => page.getByRole('slider', { name: /temperature/i });
const topPControl = page => page.getByRole('slider', { name: /top[\s-]*p|nucleus/i });
const SHORT = 'Once upon a time';
const LONG = 'One morning, a little girl named Lily went to the garden with her small dog. ' +
  'They found a red ball under a tree. Lily picked it up and asked her friend Tom to play. ' +
  'Tom smiled and ran across the grass. The dog ran after the ball, but it fell into a puddle. ' +
  'Together they washed the ball and took it home. Her mother gave them bread and milk. ' +
  'They were happy because they had helped each other and could play again tomorrow.';
const PROMPTS = [SHORT, LONG, 'Bonjour, café!'];

function close(actual, expected, tolerance = 1e-10, label = 'number') {
  assert.ok(Number.isFinite(actual) && Number.isFinite(expected), `${label}: finite values`);
  assert.ok(Math.abs(actual - expected) <= tolerance, `${label}: ${actual} vs ${expected} (±${tolerance})`);
}
function vector(actual, expected, tolerance = 1e-10) {
  assert.equal(actual.length, expected.length);
  actual.forEach((x, i) => close(x, expected[i], tolerance, `id ${i}`));
}

// Independent specification oracle. Never calls TinyLM.sampling.
function rngFrom(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6D2B79F5) >>> 0;
    let word = Math.imul(state ^ (state >>> 15), state | 1);
    word ^= word + Math.imul(word ^ (word >>> 7), word | 61);
    return ((word ^ (word >>> 14)) >>> 0) / 4294967296;
  };
}
function distribution(logits, temperature = 1, topP = 0.9) {
  const max = Math.max(...logits);
  let p;
  if (temperature === 0) {
    const best = logits.indexOf(max);
    p = logits.map((_, id) => Number(id === best));
  } else {
    const weights = logits.map(z => Math.exp((z - max) / temperature));
    const sum = weights.reduce((a, b) => a + b, 0);
    p = weights.map(w => w / sum);
  }
  const order = p.map((_, id) => id).sort((a, b) => p[b] - p[a] || a - b);
  const nucleus = [];
  let mass = 0;
  for (const id of order) {
    nucleus.push(id);
    mass += p[id];
    if (temperature === 0 || (topP < 1 && mass >= topP)) break;
  }
  const q = p.map((value, id) => nucleus.includes(id) ? value / mass : 0);
  return { p, order, nucleus, q };
}
function sample(dist, rng) {
  const u = rng(); // including greedy sampling
  let mass = 0;
  for (const id of dist.nucleus) {
    mass += dist.q[id];
    if (u < mass) return id;
  }
  return dist.nucleus.at(-1);
}

async function pageFor(t, options = {}) {
  const page = await openPage(t, chromium, { file, offline: true, ...options });
  if (options.javaScriptEnabled !== false) {
    await page.waitForFunction(() => window.TinyLM && typeof TinyLM.logits === 'function');
  }
  return page;
}
async function state(page) {
  return page.evaluate(() => ({
    tokens: Array.from(TinyLM.ui.tokens), forwardCount: TinyLM.ui.forwardCount,
    prefillCount: TinyLM.ui.prefillCount, rngDraws: TinyLM.ui.rngDraws,
  }));
}
async function encoded(page, prompt) {
  return page.evaluate(prompt => Array.from(TinyLM.encode(prompt)), prompt);
}
async function logitsAt(page, tokens) {
  // Always a fresh-prefix call; never consult the session's KV cache.
  return page.evaluate(tokens => Array.from(TinyLM.logits(tokens).at(-1)), tokens);
}
async function reset(page, prompt = SHORT, seed = 42) {
  await promptControl(page).fill(prompt);
  await promptControl(page).press('Tab');
  await seedControl(page).fill(String(seed));
  await seedControl(page).press('Tab');
  await resetControl(page).click();
  const tokens = await encoded(page, prompt);
  await eventually(async () => assert.deepEqual((await state(page)).tokens, tokens), 'prompt prefill');
  assert.equal(await chips(page).count(), 0);
  const s = await state(page);
  assert.equal(s.prefillCount, tokens.length - 1);
  assert.equal(s.forwardCount, 0);
  assert.equal(s.rngDraws, 0);
  return tokens;
}
async function sliderTo(control, value) {
  // Native keyboard actions exercise input handlers without calling page code.
  const min = Number(await control.getAttribute('min'));
  const step = Number(await control.getAttribute('step'));
  await control.focus();
  await control.press('Home');
  const count = Math.round((value - min) / step);
  for (let i = 0; i < count; i++) await control.press('ArrowRight');
  close(Number(await control.inputValue()), value);
}
async function settings(page, temperature = 1, topP = 0.9) {
  await sliderTo(temperatureControl(page), temperature);
  await sliderTo(topPControl(page), topP);
}
async function step(page) {
  const before = await state(page);
  const count = await chips(page).count();
  await stepControl(page).click();
  await eventually(async () => assert.equal(await chips(page).count(), count + 1), 'one appended token');
  const after = await state(page);
  assert.equal(after.forwardCount, before.forwardCount + 1, 'one forward per Step');
  assert.equal(after.prefillCount, before.prefillCount, 'no repeated prefill during Step');
  assert.equal(after.rngDraws, before.rngDraws + 1, 'one RNG draw per Step');
  assert.deepEqual(after.tokens.slice(0, -1), before.tokens);
  return after.tokens.at(-1);
}
async function steps(page, n) { for (let i = 0; i < n; i++) await step(page); }
async function run(page) {
  const before = await state(page);
  const count = await chips(page).count();
  await runControl(page).click();
  await page.waitForFunction(n => document.querySelectorAll('button[data-tlm-token]').length === n, count + 40, { timeout: 20000 });
  await eventually(async () => assert.equal(await resetControl(page).isEnabled(), true), 'Run finishes');
  const after = await state(page);
  assert.equal(after.forwardCount, before.forwardCount + 40);
  assert.equal(after.rngDraws, before.rngDraws + 40);
  assert.equal(after.prefillCount, before.prefillCount);
  assert.deepEqual(after.tokens.slice(0, -40), before.tokens);
}
async function trajectory(page) {
  return {
    tokens: (await state(page)).tokens,
    text: await chips(page).allTextContents(),
    ids: await chips(page).evaluateAll(nodes => nodes.map(n => Number(n.dataset.id))),
  };
}
async function predict(page, prefix, n, rng, temperature = 1, topP = 0.9) {
  const tokens = [...prefix];
  let dist;
  for (let i = 0; i < n; i++) {
    dist = distribution(await logitsAt(page, tokens), temperature, topP);
    tokens.push(sample(dist, rng));
  }
  return { tokens, dist };
}
async function tokenPiece(page, id) {
  const b64 = await page.locator('#tiny-lm-tokenizer').textContent();
  const bytes = Buffer.from(b64.replace(/\s/g, ''), 'base64');
  let offset = 4;
  for (let token = 0; token <= id; token++) {
    const length = bytes.readInt32LE(offset + 4);
    const piece = bytes.subarray(offset + 8, offset + 8 + length);
    if (token === id) return piece.toString('utf8');
    offset += 8 + length;
  }
}
function printedProbability(text, label, expected) {
  const match = text.match(new RegExp(`\\b${label}\\s*[:=]?\\s*([0-9]+(?:\\.[0-9]+)?(?:e[+-]?[0-9]+)?)\\s*(%)?`, 'i'));
  assert.ok(match, `outside-top-ten line displays ${label}`);
  const scale = match[2] ? 100 : 1;
  const [mantissa, exponent = '0'] = match[1].toLowerCase().split('e');
  const decimals = mantissa.split('.')[1]?.length ?? 0;
  const roundingUnit = 10 ** (Number(exponent) - decimals) / scale;
  close(Number(match[1]) / scale, expected, roundingUnit / 2 + 1e-10, `visible ${label}`);
}
async function chart(page, dist, drawn) {
  const rows = page.locator('ol[data-prob-chart] [data-prob-row]');
  assert.equal(await rows.count(), 10);
  for (let rank = 0; rank < 10; rank++) {
    const row = rows.nth(rank), id = dist.order[rank];
    assert.equal(Number(await row.getAttribute('data-token-id')), id, `chart rank ${rank}`);
    close(Number(await row.getAttribute('data-value')), dist.p[id], 1e-9);
    close(Number(await row.getAttribute('data-renorm')), dist.q[id], 1e-9);
    assert.equal(await row.getAttribute('data-nucleus') !== null, dist.nucleus.includes(id));
    assert.equal(await row.getAttribute('data-highlight') !== null, id === drawn);
    assert.equal(await row.isVisible(), true);
    assert.ok(normal(await row.innerText()).length, 'visible row label');
  }
  if (!dist.order.slice(0, 10).includes(drawn)) {
    const outside = page.locator('[data-tlm-drawn-outside]');
    assert.equal(await outside.isVisible(), true);
    const text = await outside.innerText();
    const piece = normal(await tokenPiece(page, drawn));
    assert.ok(text.includes(String(drawn)) || (piece && normal(text).includes(piece)) ||
      (drawn === 1 && /new story/i.test(text)), 'outside-top-ten line names drawn token');
    printedProbability(text, 'p', dist.p[drawn]);
    printedProbability(text, 'q', dist.q[drawn]);
  }
}

// Read provenance by semantic content rather than imposing an unagreed JSON schema.
function objects(value, trail = '') {
  if (!value || typeof value !== 'object') return [];
  return [{ value, trail }, ...Object.entries(value).flatMap(([key, v]) => objects(v, `${trail}/${key}`))];
}
function record(meta, filename) {
  const candidates = objects(meta).filter(({ value, trail }) =>
    /^[a-f\d]{64}$/i.test(value.sha256 ?? '') &&
    (trail + ' ' + Object.values(value).filter(v => typeof v === 'string').join(' ')).includes(filename));
  assert.equal(candidates.length, 1, `one provenance sha256 record for ${filename}`);
  return candidates[0].value;
}
function strings(value) {
  if (typeof value === 'string') return [value];
  if (!value || typeof value !== 'object') return [];
  return Object.values(value).flatMap(strings);
}
async function assets(page) {
  const meta = JSON.parse(await readAsset('provenance.json'));
  const result = { meta };
  for (const [kind, filename] of [['weights', 'stories260K.bin'], ['tokenizer', 'tok512.bin']]) {
    const block = page.locator(`script#tiny-lm-${kind}[type="application/octet-stream"]`);
    assert.equal(await block.count(), 1);
    const b64 = (await block.textContent()).trim();
    assert.match(b64, /^[A-Za-z\d+/=\s]+$/);
    const lines = b64.split(/\r?\n/).map(line => line.trim());
    for (const line of lines.slice(0, -1)) assert.equal(line.length, 120, 'base64 wrap');
    assert.ok(lines.at(-1).length > 0 && lines.at(-1).length <= 120);
    const bytes = Buffer.from(b64.replace(/\s/g, ''), 'base64');
    assert.equal(bytes.toString('base64'), b64.replace(/\s/g, ''), 'canonical complete base64');
    const hash = sha256(bytes), provenance = record(meta, filename);
    assert.equal(await block.getAttribute('data-sha256'), hash);
    assert.equal(provenance.sha256, hash);
    const size = provenance.bytes ?? provenance.byte_length ?? provenance.size_bytes ?? provenance.size ?? provenance.length;
    assert.equal(size, bytes.length, 'provenance byte length');
    const url = strings(provenance).find(s => /^https:\/\/huggingface\.co\/karpathy\/tinyllamas\/resolve\/[a-f\d]{40}\/stories260K\//.test(s));
    assert.ok(url?.endsWith(`/${filename}`), `immutable upstream URL for ${filename}`);
    result[kind] = bytes;
    result[`${kind}URL`] = url;
  }
  assert.equal(result.weightsURL.split('/')[6], result.tokenizerURL.split('/')[6], 'same model revision');
  return result;
}
function section(markdown, heading) {
  const headings = [...markdown.matchAll(/^(#{1,6})\s+(.+)$/gm)];
  const found = headings.flatMap((h, i) => {
    if (!heading.test(h[2])) return [];
    const end = headings.slice(i + 1).find(next => next[1].length <= h[1].length)?.index ?? markdown.length;
    return [markdown.slice(h.index, end)];
  });
  assert.ok(found.length, `review section ${heading}`);
  return found.join('\n');
}

test('D1: real inline checkpoint, tokenizer, public API and registered offline lab', async t => {
  const page = await pageFor(t);
  assert.equal(await page.locator('html').getAttribute('data-design-system'), 'cursus');
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'lab');
  assert.equal(await page.locator('script[src], script[type="module"], [data-lab], [data-reset]').count(), 0);
  const reserved = await page.locator('*').evaluateAll(nodes => nodes.flatMap(n => [...n.attributes].map(a => a.name)).filter(n => n.startsWith('data-budget')));
  assert.deepEqual(reserved, []);
  assert.equal(await page.locator('[data-formula]').count(), 2);
  assert.equal(await page.locator('ol[data-prob-chart]').count(), 1);
  const data = await assets(page);
  const [dim, hidden, layers, heads, kvHeads, signedVocab, seqLen] = Array.from({ length: 7 }, (_, i) => data.weights.readInt32LE(i * 4));
  assert.equal(Math.abs(signedVocab), 512);
  assert.ok(dim > 0 && hidden > 0 && layers > 0 && heads > kvHeads && kvHeads > 0 && seqLen >= 128);
  assert.equal(dim % heads, 0);
  assert.equal(heads % kvHeads, 0);
  const kvDim = dim * kvHeads / heads;
  const params = 512 * dim + layers * (2 * dim + 2 * dim * dim + 2 * dim * kvDim + 3 * dim * hidden) + dim + (signedVocab < 0 ? 512 * dim : 0);
  assert.ok(params >= 250000 && params <= 270000, 'stories260K parameter count');
  assert.equal(data.weights.length, 28 + 4 * (params + seqLen * dim / heads));
  let offset = 4;
  const maxLength = data.tokenizer.readUInt32LE(0);
  for (let id = 0; id < 512; id++) {
    assert.ok(offset + 8 <= data.tokenizer.length);
    assert.ok(Number.isFinite(data.tokenizer.readFloatLE(offset)));
    const length = data.tokenizer.readInt32LE(offset + 4);
    assert.ok(length >= 0 && length <= maxLength);
    offset += 8 + length;
    assert.ok(offset <= data.tokenizer.length);
  }
  assert.equal(offset, data.tokenizer.length, 'exactly 512 tokenizer entries');
  const config = await page.evaluate(() => TinyLM.config);
  for (const [key, expected] of Object.entries({ dim, hidden_dim: hidden, n_layers: layers, n_heads: heads, n_kv_heads: kvHeads, vocab_size: 512, seq_len: seqLen })) assert.equal(config[key], expected, key);
  assert.deepEqual(await page.evaluate(() => ['encode', 'decode', 'logits'].map(k => typeof TinyLM[k])), ['function', 'function', 'function']);
  const before = await state(page);
  const tokens = await encoded(page, 'A blue bird counted seven apples.');
  const rows = await page.evaluate(tokens => Array.from(TinyLM.logits(tokens), r => Array.from(r)), tokens);
  assert.equal(rows.length, tokens.length);
  rows.forEach(row => { assert.equal(row.length, 512); assert.ok(row.every(Number.isFinite)); });
  assert.deepEqual(await state(page), before, 'fresh logits must not touch UI cache or counters');
  assert.ok(suites.includes('tiny-lm'), 'register component-helpers suite');
  const pkg = JSON.parse(await readFile(path.join(repoRoot, 'setup/package.json'), 'utf8'));
  assert.ok(pkg.scripts.test.split(/\s+/).includes('../tools/html-pages/tests/tiny-lm.test.mjs'));
  const readme = await readAsset('README.md');
  assert.match(readme, /embed_weights\.py/);
  assert.match(readme, /(?:\d[\d.,]*\s*(?:bytes|[kKmM][bB])|page (?:size|weight))/i);
  assert.match(readme, /compiler|\bcc\b/);
  assert.match(await readFile(path.join(repoRoot, 'setup/README.md'), 'utf8'), /\bcc\b|C compiler/);
  assert.match(await readFile(path.join(repoRoot, 'setup/doctor.mjs'), 'utf8'), /['"]cc['"]/);
  const embed = await readAsset('embed_weights.py');
  assert.match(embed, /sha256/);
  assert.match(embed, /base64/);
});

test('D1: evidence is bound to the delivered page and covers every review view', async () => {
  const review = await readAsset('review.md');
  const pageHash = sha256(await readFile(file));
  assert.ok(review.includes(pageHash), 'review contains final HTML sha256');
  const shots = section(review, /screenshot|visual|views/i);
  for (const label of [/desktop/i, /laptop/i, /mobile/i, /no[- ](?:JS|JavaScript)|without JavaScript/i, /print/i]) assert.match(shots, label);
  section(review, /caption/i);
  section(review, /attribution|licen[cs]e/i);
  const host = section(review, /host.*tim|tim.*host|performance/i);
  for (const label of [/CPU|processor/i, /OS|Linux|operating system/i, /browser|Chromium/i, /trial/i, /(?:4|four)\s*[x×]|[x×]\s*4|throttl/i]) assert.match(host, label);
  assert.ok((host.match(/\b\d+(?:\.\d+)?\b/g) ?? []).length >= 20, 'raw cold and Step timings for 5 trials at each rate');
  const laptop = section(review, /2020.*laptop|laptop.*2020/i);
  assert.match(laptop, /owner|hardware|physical/i, 'real laptop evidence is an owner obligation, not a proxy claim');
});

test('A1: all per-position logits and token ids match compiled llama2.c on three prompts', async t => {
  const page = await pageFor(t);
  const data = await assets(page);
  for (const name of ['run.c', 'LICENSE']) {
    const bytes = await readFile(path.join(assetDir, 'reference', name));
    assert.equal(sha256(bytes), record(data.meta, name).sha256, `pinned ${name}`);
  }
  const cSource = await readAsset('reference/run.c');
  assert.match(cSource, /#ifndef\s+TESTING/);
  const sourceLinks = await page.locator('a[href]').evaluateAll(nodes => nodes.map(n => n.href));
  const pins = sourceLinks.flatMap(href => {
    const match = href.match(/^https:\/\/github\.com\/karpathy\/llama2\.c\/(?:blob|tree|commit)\/([a-f\d]{40})(?:\/|$)/i);
    return match ? [match[1]] : [];
  });
  assert.ok(pins.some(pin => strings(data.meta).some(value => value.includes(pin))), 'pinned llama2.c commit recorded in provenance');
  const dir = await scratch(t);
  const weights = path.join(dir, 'weights.bin'), tokenizer = path.join(dir, 'tokenizer.bin'), driver = path.join(dir, 'driver');
  await writeFile(weights, data.weights);
  await writeFile(tokenizer, data.tokenizer);
  const compiled = spawnSync('cc', ['-O2', '-std=gnu11', '-ffp-contract=off', '-o', driver, path.join(assetDir, 'reference/logits_driver.c'), '-lm'], { encoding: 'utf8', timeout: 30000 });
  assert.ifError(compiled.error); // missing cc is a failure, never a skip
  assert.equal(compiled.status, 0, compiled.stderr);
  for (const [index, prompt] of PROMPTS.entries()) {
    const run = spawnSync(driver, [weights, tokenizer, prompt], { encoding: 'utf8', timeout: 20000, maxBuffer: 16 * 1024 * 1024 });
    assert.ifError(run.error);
    assert.equal(run.status, 0, run.stderr);
    const reference = JSON.parse(run.stdout);
    const tokens = await encoded(page, prompt);
    assert.deepEqual(tokens, reference.tokens, `prompt ${index + 1}: C tokenizer`);
    if (index === 1) assert.ok(tokens.length >= 64, 'long prompt exercises cache and RoPE');
    const actual = await page.evaluate(tokens => Array.from(TinyLM.logits(tokens), row => Array.from(row)), tokens);
    assert.equal(actual.length, tokens.length);
    assert.equal(reference.logits.length, tokens.length);
    let maxError = 0;
    for (let pos = 0; pos < tokens.length; pos++) {
      assert.equal(actual[pos].length, 512);
      assert.equal(reference.logits[pos].length, 512);
      assert.ok(new Set(actual[pos]).size > 1, 'non-constant logits');
      for (let id = 0; id < 512; id++) {
        close(actual[pos][id], reference.logits[pos][id], 1e-4, `prompt ${index + 1}, pos ${pos}, id ${id}`);
        maxError = Math.max(maxError, Math.abs(actual[pos][id] - reference.logits[pos][id]));
      }
    }
    t.diagnostic(`prompt ${index + 1}: ${tokens.length} positions, max |delta| = ${maxError}`);
  }
});

test('D3: softmax, minimal nucleus, tie order, greedy sampling and mulberry32 numeric contract', async t => {
  const page = await pageFor(t);
  const cases = [
    [[2, 1, 0], 1, 1], [[2, 1, 0], 0.5, 0.9],
    [[0, 0, 0, 0], 1, 0.5], [[0, 0, 0, 0], 1, 0.500001],
    [[0, 0, 0, 0], 1, 0.05], [[1, 9, 9, -4], 0, 1],
    [[-10000, -9999, -10002, -9999], 0.7, 0.85],
    [[1000, -1000, 0], 2, 1], [[3.1, -0.4, 1.7, 2.2, -8], 1.3, 0.72],
  ];
  // Independent hand-calculated anchor, not merely two copies of an algorithm.
  vector(distribution([2, 1, 0], 1, 1).p, [0.6652409557748218, 0.24472847105479764, 0.09003057317038046]);
  vector(distribution([2, 1, 0], 0.5, 1).p, [0.8668133321973349, 0.11731042782619835, 0.015876239976466765]);
  for (const [logits, temperature, topP] of cases) {
    const expected = distribution(logits, temperature, topP);
    const actual = await page.evaluate(({ logits, temperature, topP }) => {
      const d = TinyLM.sampling.distribution(logits, temperature, topP);
      return Object.fromEntries(['p', 'q', 'order', 'nucleus'].map(k => [k, Array.from(d[k])]));
    }, { logits, temperature, topP });
    vector(actual.p, expected.p);
    vector(actual.q, expected.q);
    assert.deepEqual(actual.order, expected.order);
    assert.deepEqual(actual.nucleus, expected.nucleus);
    for (const u of [0, 0.17, 0.5, 0.999999999999]) {
      const got = await page.evaluate(({ logits, temperature, topP, u }) => {
        const d = TinyLM.sampling.distribution(logits, temperature, topP);
        let calls = 0;
        const id = TinyLM.sampling.sample(d, () => { calls++; return u; });
        return { id, calls };
      }, { logits, temperature, topP, u });
      assert.equal(got.id, sample(expected, () => u));
      assert.equal(got.calls, 1, 'including T=0');
    }
  }
  for (const seed of [0, 42, 2027, 4294967295]) {
    const rng = rngFrom(seed);
    const expected = Array.from({ length: 32 }, () => rng());
    const actual = await page.evaluate(seed => {
      const rng = TinyLM.sampling.mulberry32(seed);
      return Array.from({ length: 32 }, () => rng());
    }, seed);
    assert.deepEqual(actual, expected);
  }
});

test('D2: each Step uses one forward pass and shows the distribution that produced its token', async t => {
  const page = await pageFor(t);
  let prefix = await reset(page, 'The small fox found a green hat.', 2027);
  const rng = rngFrom(2027);
  for (const [temperature, topP] of [[1, 0.9], [0.7, 0.6], [0, 0.05], [2, 1]]) {
    await settings(page, temperature, topP);
    const before = await state(page);
    const dist = distribution(await logitsAt(page, prefix), temperature, topP);
    assert.deepEqual(await state(page), before, 'oracle call does not mutate UI');
    const expected = sample(dist, rng);
    assert.equal(await step(page), expected);
    await chart(page, dist, expected);
    prefix = [...prefix, expected];
  }
});

test('D3: native slider input updates formulas and next-token sampling; seed and prompt reset', async t => {
  const page = await pageFor(t);
  for (const [control, min, max, stepSize, initial] of [
    [temperatureControl(page), '0', '2', '0.05', '1'], [topPControl(page), '0.05', '1', '0.05', '0.9'],
  ]) {
    assert.equal(Number(await control.getAttribute('min')), Number(min));
    assert.equal(Number(await control.getAttribute('max')), Number(max));
    assert.equal(Number(await control.getAttribute('step')), Number(stepSize));
    assert.equal(Number(await control.inputValue()), Number(initial));
  }
  assert.equal(Number(await seedControl(page).inputValue()), 42);
  let prefix = await reset(page);
  const rng = rngFrom(42);
  for (const mode of ['keyboard', 'pointer']) {
    if (mode === 'keyboard') await settings(page, 0.7, 0.55);
    else {
      for (const control of [temperatureControl(page), topPControl(page)]) {
        const box = await control.boundingBox();
        assert.ok(box && box.width > 0);
        await control.click({ position: { x: box.width * 0.8, y: box.height / 2 } });
      }
    }
    const temperature = Number(await temperatureControl(page).inputValue());
    const topP = Number(await topPControl(page).inputValue());
    for (const [control, value, expression] of [[temperatureControl(page), temperature, /exp|softmax/i], [topPControl(page), topP, /Σ|∑|sum|mass|renorm/i]]) {
      const output = control.locator('xpath=ancestor::*[@data-formula][1]').locator('[data-formula-output]');
      const text = await output.innerText();
      assert.match(text, expression);
      const numbers = (text.match(/\d+(?:\.\d+)?/g) ?? []).map(Number);
      assert.ok(numbers.some(n => Math.abs(n - value) < 1e-10), 'formula substitutes live slider value');
    }
    const dist = distribution(await logitsAt(page, prefix), temperature, topP);
    const expected = sample(dist, rng);
    assert.equal(await step(page), expected);
    await chart(page, dist, expected);
    prefix.push(expected);
  }
  await seedControl(page).fill('314159');
  await seedControl(page).press('Tab');
  await eventually(async () => assert.equal(await chips(page).count(), 0), 'changing seed clears generation');
  assert.equal((await state(page)).rngDraws, 0);
  await step(page);
  await promptControl(page).fill('A cat sat beside the river.');
  await promptControl(page).press('Tab');
  await eventually(async () => assert.equal(await chips(page).count(), 0), 'changing prompt clears generation');
  assert.equal((await state(page)).rngDraws, 0);
  for (const invalid of ['-1', '4294967296', '1.5', '']) {
    await seedControl(page).fill(invalid);
    await seedControl(page).press('Tab');
    // A visible native validation bubble or application message is acceptable;
    // silence, wrapping, truncating or accepting the bad seed is not.
    const nativeInvalid = await seedControl(page).evaluate(el => !el.checkValidity() && !!el.validationMessage);
    const messages = page.locator('[role="alert"], [role="status"], [aria-live], [data-tlm-error]');
    let visibleMessage = false;
    for (const message of await messages.all()) {
      if (await message.isVisible() && /seed|integer|invalid|32|4294967295/i.test(await message.innerText())) visibleMessage = true;
    }
    assert.ok(nativeInvalid || visibleMessage, `reject seed ${JSON.stringify(invalid)} with a message`);
    assert.equal(await chips(page).count(), 0);
  }
});

test('D2: Run yields, locks controls, appends forty tokens and respects the context boundary', async t => {
  const page = await pageFor(t);
  await reset(page);
  // Observe the yielded interval in-page, avoiding a race with automation IPC.
  await page.evaluate(() => {
    window.__runObservations = [];
    const timer = setInterval(() => {
      const count = document.querySelectorAll('button[data-tlm-token]').length;
      if (count > 0 && count < 40) {
        const controls = [...document.querySelectorAll('input, textarea, select, button')]
          .filter(el => el.matches('input, textarea, select, [data-tlm-token], [data-formula-reset]') ||
            /^(?:step|run|reset)\b/i.test((el.getAttribute('aria-label') || el.textContent).trim()));
        window.__runObservations.push({ count, enabled: controls.filter(el => !el.disabled).map(el => el.outerHTML) });
      }
      if (count >= 40) clearInterval(timer);
    }, 0);
  });
  await run(page);
  const observations = await page.evaluate(() => window.__runObservations);
  assert.ok(observations.length > 0, 'Run yields between tokens');
  assert.ok(observations.every(o => o.enabled.length === 0), 'other controls disabled while Run is active');
  const seqLen = await page.evaluate(() => TinyLM.config.seq_len);
  // Find a prompt with 1..39 positions left using the real tokenizer. This
  // exercises the guard through the UI, without mutating its private state.
  const near = await page.evaluate(seqLen => {
    let prompt = '';
    for (let n = 0; n < seqLen * 2; n++) {
      prompt += ' cat';
      const length = TinyLM.encode(prompt).length;
      const remaining = seqLen - (length - 1);
      if (remaining > 0 && remaining < 40) return { prompt, remaining };
    }
    return null;
  }, seqLen);
  assert.ok(near, 'construct near-capacity prompt');
  await reset(page, near.prompt);
  assert.equal(await runControl(page).isEnabled(), false);
  assert.match(await page.locator('body').innerText(), /(?:40|forty).*(?:remain|position|space|token)|(?:remain|position|space|token).*?(?:40|forty)/i);
  await steps(page, near.remaining);
  assert.equal(await stepControl(page).isEnabled(), false, 'no forward beyond seq_len');
  assert.equal(await runControl(page).isEnabled(), false);
});

test('D2: samples outside the top ten are named; a natural BOS does not end generation', async t => {
  const page = await pageFor(t);
  const prompt = 'They were happy and went home. The end.';
  const prefix = await reset(page, prompt);
  await settings(page, 2, 1);
  const dist = distribution(await logitsAt(page, prefix), 2, 1);
  let outsideSeed, outsideId;
  for (let candidate = 0; candidate < 10000; candidate++) {
    const id = sample(dist, rngFrom(candidate));
    if (!dist.order.slice(0, 10).includes(id)) { outsideSeed = candidate; outsideId = id; break; }
  }
  assert.notEqual(outsideSeed, undefined, 'find a real draw outside the displayed ten');
  await reset(page, prompt, outsideSeed);
  assert.equal(await step(page), outsideId);
  await chart(page, dist, outsideId);
  // Choose input seeds, not output tokens. The real production sampler must
  // land in the independently computed BOS interval without any monkeypatch.
  const bosRank = dist.nucleus.indexOf(1);
  assert.ok(bosRank >= 0);
  const lower = dist.nucleus.slice(0, bosRank).reduce((sum, id) => sum + dist.q[id], 0);
  const upper = lower + dist.q[1];
  let seed;
  for (let candidate = 0; candidate < 1000000; candidate++) {
    const u = rngFrom(candidate)();
    if (u >= lower && u < upper) { seed = candidate; break; }
  }
  assert.notEqual(seed, undefined, 'find a real seed that samples BOS');
  await reset(page, prompt, seed);
  assert.equal(await step(page), 1);
  const chip = chips(page).last();
  assert.equal(await chip.isVisible(), true);
  assert.match(await chip.innerText(), /new story/i);
  await chart(page, dist, 1);
  await reset(page, prompt, seed);
  await run(page);
  assert.equal(Number(await chips(page).first().getAttribute('data-id')), 1);
  assert.equal(await chips(page).count(), 40, 'BOS does not terminate Run');
  t.diagnostic(`Natural BOS witness: seed ${seed}, T=2, top-p=1; ${prompt}`);
});

test('D2: rewind at every generated position preserves prefix and resamples the tail from the continuing RNG', async t => {
  const page = await pageFor(t);
  const seed = 42;
  const initial = await reset(page, SHORT, seed);
  await settings(page, 1.2, 0.95);
  const originalPrediction = await predict(page, initial, 12, rngFrom(seed), 1.2, 0.95);
  let divergence;
  for (let k = 0; k < 12; k++) {
    await reset(page, SHORT, seed);
    await steps(page, 12);
    const old = await trajectory(page);
    assert.deepEqual(old.tokens, originalPrediction.tokens);
    const keep = initial.length + k;
    const rng = rngFrom(seed);
    for (let i = 0; i < 12; i++) rng();
    const expected = await predict(page, old.tokens.slice(0, keep), 12 - k, rng, 1.2, 0.95);
    const oldTailText = [];
    for (const id of old.tokens.slice(keep)) {
      let piece = await tokenPiece(page, id);
      const byte = piece.match(/^<0x([\da-f]{2})>$/i);
      if (byte) piece = Buffer.from([Number.parseInt(byte[1], 16)]).toString('utf8');
      // BOS has the agreed human-readable label; other pieces come from the
      // actual tokenizer, rather than any optional ids appended to chip labels.
      oldTailText.push(id === 1 ? 'new story' : normal(piece));
    }
    const before = await state(page);
    const chip = chips(page).nth(k);
    const positions = await chips(page).evaluateAll(nodes => nodes.map(n => Number(n.dataset.pos)));
    for (let i = 1; i < positions.length; i++) assert.equal(positions[i], positions[i - 1] + 1);
    if (k % 2) { await chip.focus(); await chip.press('Enter'); }
    else await chip.click();
    await eventually(async () => assert.equal((await state(page)).rngDraws, before.rngDraws + 12 - k), `rewind ${k} completes`);
    await eventually(async () => assert.equal(await resetControl(page).isEnabled(), true));
    const after = await state(page);
    assert.equal(after.forwardCount, before.forwardCount + 12 - k);
    assert.equal(after.prefillCount, before.prefillCount, 'rewind reuses valid cache prefix');
    assert.deepEqual(after.tokens.slice(0, keep), old.tokens.slice(0, keep));
    assert.deepEqual(after.tokens, expected.tokens, `continuing RNG at generated position ${k}`);
    assert.equal(await chips(page).count(), 12);
    const previous = page.locator('[data-tlm-previous]');
    assert.equal(await previous.isVisible(), true);
    const text = normal(await previous.innerText());
    let at = 0;
    for (const piece of oldTailText.filter(Boolean)) {
      const found = text.indexOf(piece, at);
      assert.ok(found >= at, 'previous branch contains discarded token text in order');
      at = found + piece.length;
    }
    await chart(page, expected.dist, expected.tokens.at(-1));
    if (JSON.stringify(expected.tokens) !== JSON.stringify(old.tokens)) divergence ??= k;
  }
  assert.notEqual(divergence, undefined, 'at least one naturally divergent branch');
  t.diagnostic(`Divergence: seed ${seed}, T=1.2, top-p=0.95, generated position ${divergence}`);
});

test('A2: seeds reproduce text across independent contexts, reload, Reset, Steps and Run', async t => {
  const first = await pageFor(t), second = await pageFor(t);
  const outputs = [];
  for (const prompt of [SHORT, 'A little dog found a blue box.']) {
    for (const seed of [42, 271828]) {
      const prefix = await reset(first, prompt, seed);
      await settings(first);
      const prediction = await predict(first, prefix, 40, rngFrom(seed));
      await run(first);
      const baseline = await trajectory(first);
      assert.deepEqual(baseline.tokens, prediction.tokens, 'independent sampler prediction');
      assert.deepEqual(baseline.ids, prediction.tokens.slice(prefix.length));
      await reset(second, prompt, seed);
      await settings(second);
      await steps(second, 40);
      assert.deepEqual(await trajectory(second), baseline, 'fresh context, forty Steps');
      await resetControl(first).click();
      await run(first);
      assert.deepEqual(await trajectory(first), baseline, 'Reset clears RNG and cache');
      await second.reload();
      await reset(second, prompt, seed);
      await settings(second);
      await run(second);
      assert.deepEqual(await trajectory(second), baseline, 'reload');
      outputs.push(baseline);
    }
  }
  assert.notDeepEqual(outputs[0].text, outputs[1].text, 'documented seeds 42 and 271828 yield different predicted text');
  t.diagnostic('Seed contrast: Once upon a time; T=1, top-p=0.9; seeds 42 and 271828.');
});

test('A2: an identical Step/Run/rewind action sequence replays with no cache or RNG leakage', async t => {
  const pages = [await pageFor(t), await pageFor(t)];
  const results = [];
  for (const page of pages) {
    const prefix = await reset(page, 'Tom opened the door.', 7);
    await settings(page, 0.85, 0.8);
    const rng = rngFrom(7);
    let expected = await predict(page, prefix, 42, rng, 0.85, 0.8);
    await steps(page, 2);
    await run(page);
    assert.deepEqual((await state(page)).tokens, expected.tokens);
    // Rewind just the final three positions after the mixed Step/Run history.
    expected = await predict(page, expected.tokens.slice(0, -3), 3, rng, 0.85, 0.8);
    const draws = (await state(page)).rngDraws;
    await chips(page).nth(39).click();
    await eventually(async () => assert.equal((await state(page)).rngDraws, draws + 3));
    assert.deepEqual((await state(page)).tokens, expected.tokens);
    results.push(await trajectory(page));
  }
  assert.deepEqual(results[0], results[1]);
});

test('D4: the caption is visible with JS, without JS and in print, and quoted in the prose review', async t => {
  const texts = [];
  for (const javaScriptEnabled of [true, false]) {
    const page = await pageFor(t, { javaScriptEnabled });
    const caption = page.getByText(/Trained only on TinyStories/i).filter({ hasText: /mechanism.*not the capability/i });
    assert.equal(await caption.count(), 1);
    assert.equal(await caption.isVisible(), true);
    texts.push(normal(await caption.innerText()));
    await page.emulateMedia({ media: 'print' });
    assert.equal(await caption.isVisible(), true);
  }
  assert.equal(texts[0], texts[1]);
  const review = section(await readAsset('review.md'), /caption/i);
  assert.ok(normal(review).includes(texts[0]), 'prose review quotes actual caption');
});

test('A4: visible pinned attribution and the full MIT notice cover weights, tokenizer and code', async t => {
  const page = await pageFor(t);
  const { meta, weightsURL } = await assets(page);
  const footer = page.locator('footer');
  assert.equal(await footer.isVisible(), true);
  const text = await footer.innerText();
  for (const name of [/Andrej Karpathy/i, /stories260K/, /tok512/, /tinyllamas/, /llama2\.c/, /run\.c/, /MIT/]) assert.match(text, name);
  const links = await footer.locator('a[href]').evaluateAll(nodes => nodes.map(n => n.href));
  const hfRevision = weightsURL.split('/')[6];
  assert.ok(links.some(href => href.startsWith('https://huggingface.co/karpathy/tinyllamas/') && href.includes(hfRevision)));
  const allMeta = JSON.stringify(meta);
  assert.ok(links.some(href => {
    const m = href.match(/^https:\/\/github\.com\/karpathy\/llama2\.c\/(?:blob|tree|commit)\/([a-f\d]{40})(?:\/|$)/);
    return m && allMeta.includes(m[1]);
  }), 'code reading link uses recorded commit');
  assert.ok(objects(meta).some(({ value }) => Object.entries(value).some(([key, value]) => /license/i.test(key) && typeof value === 'string' && value.toLowerCase() === 'mit')), 'model card license field');
  const license = normal(await readAsset('reference/LICENSE'));
  // Upstream's notice uses "Andrej"; the footer above credits Andrej Karpathy in full.
  assert.match(license, /Copyright \(c\) 2023 Andrej\b/);
  assert.match(license, /Permission is hereby granted/);
  assert.match(license, /THE SOFTWARE IS PROVIDED "AS IS"/);
  const notices = await page.locator('details').all();
  let found = false;
  for (const details of notices) {
    if (!(await details.textContent()).includes('Permission is hereby granted')) continue;
    await details.evaluate(el => { el.open = true; });
    const full = normal(await details.innerText());
    const summary = normal(await details.locator('summary').innerText());
    assert.equal(full.slice(summary.length).trim(), license, 'complete notice byte-equal after whitespace normalization');
    found = true;
  }
  assert.ok(found, 'full MIT notice in disclosure');
  const review = section(await readAsset('review.md'), /attribution|licen[cs]e/i);
  for (const term of [/weights|stories260K/i, /tokenizer|tok512/i, /code|port|run\.c/i, /MIT/]) assert.match(review, term);
});

test('A3: offline file navigation and no runtime network, worker or WASM APIs', async t => {
  const page = await pageFor(t);
  assert.ok(page.url().startsWith('file://'));
  const source = await page.locator('script:not([type="application/octet-stream"])').allTextContents();
  for (const script of source) {
    assert.doesNotMatch(script, /\b(?:fetch|XMLHttpRequest|WebSocket|WebAssembly|Worker|SharedWorker)\s*(?:\(|\.)|\bimport\s*\(/, 'pure JS on main thread');
  }
  const requests = [];
  page.on('request', req => requests.push(req.url()));
  await page.reload();
  await reset(page);
  await step(page);
  assert.ok(requests.length > 0);
  assert.ok(requests.every(url => url.startsWith('file://')), JSON.stringify(requests));
});

test('A3: five cold first-painted-token trials at native speed and 4x CPU proxy are under one second', async t => {
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const trials = [];
  for (const rate of [1, 4]) {
    for (let trial = 0; trial < 5; trial++) {
      const context = await browser.newContext({ offline: true, viewport: { width: 1280, height: 720 } });
      try {
        const page = await context.newPage();
        const requests = [], errors = [];
        page.on('request', request => requests.push(request.url()));
        page.on('pageerror', error => errors.push(error.message));
        const cdp = await context.newCDPSession(page);
        await cdp.send('Emulation.setCPUThrottlingRate', { rate });
        await page.addInitScript(() => {
          window.__firstTokenTiming = null;
          // Schedule the click from DOMContentLoaded, after all page listeners
          // have run. A microtask here can precede later DCL listeners.
          document.addEventListener('DOMContentLoaded', () => setTimeout(() => {
            const step = [...document.querySelectorAll('button')].find(el => /^step\b/i.test((el.getAttribute('aria-label') || el.textContent).trim()));
            if (!step || step.disabled) { window.__firstTokenTiming = { error: 'Step not ready at DOMContentLoaded' }; return; }
            const start = performance.now();
            const observe = () => {
              const chip = document.querySelector('button[data-tlm-token]');
              if (!chip || !chip.getClientRects().length || getComputedStyle(chip).visibility === 'hidden') { requestAnimationFrame(observe); return; }
              // A second animation frame crosses a paint opportunity.
              requestAnimationFrame(() => { window.__firstTokenTiming = { coldMs: performance.now(), stepMs: performance.now() - start }; });
            };
            step.click();
            requestAnimationFrame(observe);
          }, 0), { once: true });
        });
        await page.goto(pathToFileURL(file).href, { waitUntil: 'domcontentloaded' });
        await page.waitForFunction(() => window.__firstTokenTiming !== null, null, { timeout: 5000 });
        const timing = await page.evaluate(() => window.__firstTokenTiming);
        assert.ok(!timing.error, timing.error);
        assert.deepEqual(errors, []);
        assert.ok(requests.length && requests.every(url => url.startsWith('file://')));
        assert.ok(timing.coldMs > 0 && timing.coldMs < 1000, `rate ${rate}, trial ${trial}: cold ${timing.coldMs} ms`);
        assert.ok(timing.stepMs > 0 && timing.stepMs < 1000, `rate ${rate}, trial ${trial}: Step ${timing.stepMs} ms`);
        trials.push({ rate, trial: trial + 1, ...timing });
      } finally { await context.close(); }
    }
  }
  t.diagnostic(JSON.stringify({ cpu: cpus()[0]?.model, os: `${platform()} ${release()}`, browser: browser.version(), trials }));
  t.diagnostic('Host/4x measurements are a proxy only. A3 requires separate owner evidence from an identified 2020 laptop.');
});
