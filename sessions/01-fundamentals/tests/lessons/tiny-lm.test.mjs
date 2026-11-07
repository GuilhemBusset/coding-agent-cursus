import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../../../../tools/html-pages/browser.mjs';
import { repoRoot, scratch, eventually } from '../../../../tools/html-pages/tests/component-helpers.mjs';

/* The tiny-LM lab: the real stories260K checkpoint, embedded in the page, run by a JavaScript port
 * of llama2.c's run.c. Its public surface: TinyLM.encode(prompt) (with BOS), TinyLM.logits(tokens)
 * (one row per position, fresh prefix), TinyLM.sampling.distribution(logits, T, topP) ->
 * {p, order, nucleus, q} and sample(distribution, rng) -> id, and TinyLM.ui's counters. The
 * forward pass is checked against compiled run.c, the sampler and every generated token against
 * the independent oracle below. Layout, axe, no-JS and print are check-page.mjs's job. */
const relative = 'sessions/01-fundamentals/cursus/labs/tiny-lm';
const file = path.join(repoRoot, `${relative}.html`);
const assetDir = path.join(repoRoot, relative);
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
const BOS = 1;

// The checkpoint and tokenizer as the page embeds them (base64 in script blocks).
let embeddedBytes;
async function embedded() {
  if (embeddedBytes) return embeddedBytes;
  const html = await readFile(file, 'utf8');
  const block = kind => {
    const match = html.match(new RegExp(`<script\\b[^>]*\\bid="tiny-lm-${kind}"[^>]*>([\\s\\S]*?)</script>`));
    assert.ok(match, `embedded ${kind} block`);
    return Buffer.from(match[1].replace(/\s/g, ''), 'base64');
  };
  embeddedBytes = { weights: block('weights'), tokenizer: block('tokenizer') };
  return embeddedBytes;
}
// tok512.bin: max length, then per token a float score, an int32 length and the UTF-8 piece.
async function piece(id) {
  const bytes = (await embedded()).tokenizer;
  let offset = 4;
  for (let token = 0; token <= id; token++) {
    const length = bytes.readInt32LE(offset + 4);
    if (token === id) {
      const text = bytes.subarray(offset + 8, offset + 8 + length).toString('utf8');
      const byte = text.match(/^<0x([\da-f]{2})>$/i);
      return byte ? Buffer.from([Number.parseInt(byte[1], 16)]).toString('utf8') : text;
    }
    offset += 8 + length;
  }
}

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
  const u = rng(); // one draw, including greedy sampling
  let mass = 0;
  for (const id of dist.nucleus) {
    mass += dist.q[id];
    if (u < mass) return id;
  }
  return dist.nucleus.at(-1);
}

// ---- One browser for the file, a fresh context per test. ----
let browser;
after(() => browser?.close());
async function pageFor(t) {
  browser ??= await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const errors = [];
  t.after(async () => { await context.close(); assert.deepEqual(errors, [], 'no runtime errors or remote requests'); });
  await context.route(/^(https?|wss?):/i, route => { errors.push(`remote request: ${route.request().url()}`); return route.abort(); });
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(pathToFileURL(file).href);
  await page.waitForFunction(() => window.TinyLM && typeof TinyLM.logits === 'function');
  return page;
}
async function state(page) {
  return page.evaluate(() => ({
    tokens: Array.from(TinyLM.ui.tokens), forwardCount: TinyLM.ui.forwardCount,
    prefillCount: TinyLM.ui.prefillCount, rngDraws: TinyLM.ui.rngDraws,
  }));
}
const encoded = (page, prompt) => page.evaluate(prompt => Array.from(TinyLM.encode(prompt)), prompt);
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
  assert.equal(s.prefillCount, tokens.length - 1, 'prefill forwards every prompt token but the last');
  assert.equal(s.forwardCount, 0);
  assert.equal(s.rngDraws, 0);
  return tokens;
}
async function settings(page, temperature = 1, topP = 0.9) {
  for (const [control, value] of [[temperatureControl(page), temperature], [topPControl(page), topP]]) {
    await control.fill(String(value)); // dispatches input and change, as dragging does
    close(Number(await control.inputValue()), value);
  }
}
async function step(page) {
  const before = await state(page), count = await chips(page).count();
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
  const before = await state(page), count = await chips(page).count();
  await runControl(page).click();
  await page.waitForFunction(n => document.querySelectorAll('button[data-tlm-token]').length === n, count + 40, { timeout: 20000 });
  await eventually(async () => assert.equal(await resetControl(page).isEnabled(), true), 'Run finishes');
  const after = await state(page);
  assert.equal(after.forwardCount, before.forwardCount + 40);
  assert.equal(after.rngDraws, before.rngDraws + 40);
  assert.equal(after.prefillCount, before.prefillCount);
  assert.deepEqual(after.tokens.slice(0, -40), before.tokens);
  return after.tokens;
}
// Replays the oracle sampler over the page's own tokens from position `from` on, drawing from `rng`
// (which carries on across calls, like the page's stream). One logits call: row i is the
// distribution of token i + 1. Returns the distribution of the last token.
async function verify(page, tokens, from, rng, temperature, topP) {
  const rows = await page.evaluate(tokens => Array.from(TinyLM.logits(tokens), row => Array.from(row)), tokens.slice(0, -1));
  let dist;
  for (let pos = from; pos < tokens.length; pos++) {
    dist = distribution(rows[pos - 1], temperature, topP);
    assert.equal(tokens[pos], sample(dist, rng), `token at position ${pos} is the oracle's draw`);
  }
  return dist;
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
// The chart shows the top ten of the distribution that produced the drawn token, and names a
// drawn token from outside the ten with its p and q.
async function chart(page, dist, drawn) {
  const rows = await page.locator('ol[data-prob-chart] [data-prob-row]').evaluateAll(els => els.map(el => ({
    id: Number(el.getAttribute('data-token-id')), p: Number(el.getAttribute('data-value')), q: Number(el.getAttribute('data-renorm')),
    nucleus: el.hasAttribute('data-nucleus'), highlight: el.hasAttribute('data-highlight'), visible: el.checkVisibility(),
  })));
  assert.equal(rows.length, 10);
  rows.forEach((row, rank) => {
    const id = dist.order[rank];
    assert.equal(row.id, id, `chart rank ${rank}`);
    close(row.p, dist.p[id], 1e-9); close(row.q, dist.q[id], 1e-9);
    assert.equal(row.nucleus, dist.nucleus.includes(id));
    assert.equal(row.highlight, id === drawn);
    assert.ok(row.visible);
  });
  const outside = page.locator('[data-tlm-drawn-outside]');
  assert.equal(await outside.isVisible(), !dist.order.slice(0, 10).includes(drawn), 'outside-top-ten line iff the draw is outside');
  if (dist.order.slice(0, 10).includes(drawn)) return;
  const text = await outside.innerText();
  assert.ok(text.includes(String(drawn)) || normal(text).includes(normal(await piece(drawn))), 'outside-top-ten line names the drawn token');
  printedProbability(text, 'p', dist.p[drawn]);
  printedProbability(text, 'q', dist.q[drawn]);
}

test('the page embeds the pinned stories260K weights and tokenizer, and vendors the pinned run.c', async () => {
  const meta = JSON.parse(await readFile(path.join(assetDir, 'provenance.json'), 'utf8'));
  const bytes = await embedded();
  for (const [name, record] of [['weights', meta.model.files.weights], ['tokenizer', meta.model.files.tokenizer]]) {
    assert.equal(sha256(bytes[name]), record.sha256, `embedded ${name} is ${record.path}`);
    assert.equal(bytes[name].length, record.bytes, `${name} byte length`);
  }
  assert.equal(sha256(await readFile(path.join(assetDir, 'reference/run.c'))), meta.code.files.run_c.sha256, 'pinned run.c');
});

test('logits at every position and token ids match compiled llama2.c run.c on three prompts', async t => {
  const page = await pageFor(t), data = await embedded();
  const dir = await scratch(t);
  const weights = path.join(dir, 'weights.bin'), tokenizer = path.join(dir, 'tokenizer.bin'), driver = path.join(dir, 'driver');
  await writeFile(weights, data.weights);
  await writeFile(tokenizer, data.tokenizer);
  const compiled = spawnSync('cc', ['-O2', '-std=gnu11', '-ffp-contract=off', '-o', driver, path.join(assetDir, 'reference/logits_driver.c'), '-lm'], { encoding: 'utf8', timeout: 30000 });
  assert.ifError(compiled.error); // missing cc is a failure, never a skip
  assert.equal(compiled.status, 0, compiled.stderr);
  // A short prompt, a long one (KV cache and RoPE over many positions), and UTF-8 byte fallback.
  for (const [index, prompt] of [SHORT, LONG, 'Bonjour, café!'].entries()) {
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
    for (let pos = 0; pos < tokens.length; pos++) {
      assert.equal(actual[pos].length, 512);
      assert.ok(new Set(actual[pos]).size > 1, 'non-constant logits');
      for (let id = 0; id < 512; id++) {
        if (!(Math.abs(actual[pos][id] - reference.logits[pos][id]) <= 1e-4)) close(actual[pos][id], reference.logits[pos][id], 1e-4, `prompt ${index + 1}, pos ${pos}, id ${id}`);
      }
    }
  }
});

test('sampler: softmax, minimal nucleus, tie order and greedy sampling match the oracle', async t => {
  const page = await pageFor(t);
  const cases = [
    [[2, 1, 0], 1, 1], [[2, 1, 0], 0.5, 0.9],
    [[0, 0, 0, 0], 1, 0.5], [[0, 0, 0, 0], 1, 0.500001],
    [[0, 0, 0, 0], 1, 0.05], [[1, 9, 9, -4], 0, 1],
    [[-10000, -9999, -10002, -9999], 0.7, 0.85],
    [[1000, -1000, 0], 2, 1], [[3.1, -0.4, 1.7, 2.2, -8], 1.3, 0.72],
  ];
  const draws = [0, 0.17, 0.5, 0.999999999999];
  // Hand-calculated anchors, so the oracle is not merely a second copy of an algorithm.
  vector(distribution([2, 1, 0], 1, 1).p, [0.6652409557748218, 0.24472847105479764, 0.09003057317038046]);
  vector(distribution([2, 1, 0], 0.5, 1).p, [0.8668133321973349, 0.11731042782619835, 0.015876239976466765]);
  const results = await page.evaluate(({ cases, draws }) => cases.map(([logits, temperature, topP]) => {
    const d = TinyLM.sampling.distribution(logits, temperature, topP);
    return { ...Object.fromEntries(['p', 'q', 'order', 'nucleus'].map(k => [k, Array.from(d[k])])),
      samples: draws.map(u => { let calls = 0; const id = TinyLM.sampling.sample(d, () => { calls++; return u; }); return { id, calls }; }) };
  }), { cases, draws });
  cases.forEach(([logits, temperature, topP], i) => {
    const expected = distribution(logits, temperature, topP), actual = results[i];
    vector(actual.p, expected.p);
    vector(actual.q, expected.q);
    assert.deepEqual(actual.order, expected.order);
    assert.deepEqual(actual.nucleus, expected.nucleus);
    assert.deepEqual(actual.samples, draws.map(u => ({ id: sample(expected, () => u), calls: 1 })), 'one draw per sample, including T=0');
  });
});

test('each Step runs one forward pass, draws the oracle token and charts its distribution; a new seed or prompt starts over', async t => {
  const page = await pageFor(t);
  let prefix = await reset(page, 'The small fox found a green hat.', 2027);
  const rng = rngFrom(2027);
  // A nucleus cut, greedy, and no cut.
  for (const [temperature, topP] of [[0.7, 0.6], [0, 0.05], [2, 1]]) {
    await settings(page, temperature, topP);
    const drawn = await step(page);
    prefix = [...prefix, drawn];
    const dist = await verify(page, prefix, prefix.length - 1, rng, temperature, topP);
    await chart(page, dist, drawn);
  }
  await seedControl(page).fill('314159');
  await seedControl(page).press('Tab');
  await eventually(async () => assert.equal(await chips(page).count(), 0), 'changing the seed clears the generation');
  assert.equal((await state(page)).rngDraws, 0);
  await step(page);
  await promptControl(page).fill('A cat sat beside the river.');
  await promptControl(page).press('Tab');
  await eventually(async () => assert.equal(await chips(page).count(), 0), 'changing the prompt clears the generation');
  assert.equal((await state(page)).rngDraws, 0);
});

test('Run appends forty tokens with controls locked; Steps, Run and rewind continue one seeded stream; Reset replays it; the context is never overrun', async t => {
  const page = await pageFor(t), seed = 7, temperature = 0.85, topP = 0.8;
  const prefix = await reset(page, 'Tom opened the door.', seed);
  await settings(page, temperature, topP);
  await steps(page, 2);
  // Observe the yielded interval in-page, avoiding a race with automation IPC.
  await page.evaluate(base => {
    window.__runObservations = [];
    const timer = setInterval(() => {
      const count = document.querySelectorAll('button[data-tlm-token]').length;
      if (count > base && count < base + 40) {
        const controls = [...document.querySelectorAll('input, textarea, select, button')]
          .filter(el => el.matches('input, textarea, select, [data-tlm-token], [data-formula-reset]') ||
            /^(?:step|run|reset)\b/i.test((el.getAttribute('aria-label') || el.textContent).trim()));
        window.__runObservations.push(controls.filter(el => !el.disabled).map(el => el.outerHTML));
      }
      if (count >= base + 40) clearInterval(timer);
    }, 0);
  }, 2);
  const tokens = await run(page);
  const observations = await page.evaluate(() => window.__runObservations);
  assert.ok(observations.length > 0, 'Run yields between tokens');
  assert.ok(observations.every(enabled => enabled.length === 0), 'every control is disabled while Run is active');
  const rng = rngFrom(seed);
  await verify(page, tokens, prefix.length, rng, temperature, topP);
  // Rewind the last three positions: the tail is redrawn from the continuing stream.
  const draws = (await state(page)).rngDraws;
  await chips(page).nth(39).click();
  await eventually(async () => assert.equal((await state(page)).rngDraws, draws + 3), 'rewind redraws three tokens');
  const rewound = (await state(page)).tokens;
  assert.deepEqual(rewound.slice(0, -3), tokens.slice(0, -3));
  await verify(page, rewound, rewound.length - 3, rng, temperature, topP);
  await resetControl(page).click();
  await eventually(async () => assert.equal(await chips(page).count(), 0), 'Reset clears the generation');
  assert.deepEqual(await run(page), tokens.slice(0, prefix.length + 40), 'Reset restarts the seeded stream and the cache');
  // Near the end of the context, Run is refused and Step stops at the last position.
  const near = await page.evaluate(() => {
    // Binary search for the longest repetition that still leaves a position free.
    const remaining = n => TinyLM.config.seq_len - (TinyLM.encode(' cat'.repeat(n)).length - 1);
    let lo = 1, hi = TinyLM.config.seq_len;
    while (lo < hi) { const mid = Math.ceil((lo + hi) / 2); if (remaining(mid) > 0) lo = mid; else hi = mid - 1; }
    const left = remaining(lo);
    return left > 0 && left < 40 ? { prompt: ' cat'.repeat(lo), remaining: left } : null;
  });
  assert.ok(near, 'construct a near-capacity prompt with the real tokenizer');
  await reset(page, near.prompt);
  assert.equal(await runControl(page).isEnabled(), false, 'Run needs forty free positions');
  await steps(page, near.remaining);
  assert.equal(await stepControl(page).isEnabled(), false, 'no forward pass beyond seq_len');
  assert.equal(await runControl(page).isEnabled(), false);
});

test('rewinding keeps the prefix, redraws the tail from the continuing stream and shows the discarded branch', async t => {
  const page = await pageFor(t), seed = 42, temperature = 1.2, topP = 0.95;
  const prefix = await reset(page, SHORT, seed);
  await settings(page, temperature, topP);
  await steps(page, 12);
  const rng = rngFrom(seed);
  let tokens = (await state(page)).tokens, diverged = false;
  await verify(page, tokens, prefix.length, rng, temperature, topP);
  // The first generated position by pointer, a later one by keyboard.
  for (const [k, keyboard] of [[0, false], [7, true]]) {
    const keep = prefix.length + k, before = await state(page);
    const chip = chips(page).nth(k);
    if (keyboard) { await chip.focus(); await chip.press('Enter'); }
    else await chip.click();
    await eventually(async () => assert.equal((await state(page)).rngDraws, before.rngDraws + 12 - k), `rewind at ${k} completes`);
    await eventually(async () => assert.equal(await resetControl(page).isEnabled(), true));
    const after = await state(page);
    assert.equal(after.forwardCount, before.forwardCount + 12 - k);
    assert.equal(after.prefillCount, before.prefillCount, 'rewind reuses the cached prefix');
    assert.equal(after.tokens.length, tokens.length);
    assert.deepEqual(after.tokens.slice(0, keep), tokens.slice(0, keep));
    const dist = await verify(page, after.tokens, keep, rng, temperature, topP);
    await chart(page, dist, after.tokens.at(-1));
    const shown = normal(await page.locator('[data-tlm-previous]').innerText());
    let at = 0;
    for (const id of tokens.slice(keep)) {
      const text = id === BOS ? 'new story' : normal(await piece(id));
      if (!text) continue;
      const found = shown.indexOf(text, at);
      assert.ok(found >= at, `the previous branch shows the discarded tokens in order: ${shown}`);
      at = found + text.length;
    }
    diverged ||= JSON.stringify(after.tokens) !== JSON.stringify(tokens);
    tokens = after.tokens;
  }
  assert.ok(diverged, 'at least one naturally divergent branch');
});

test('a draw from outside the top ten is named with its p and q; a drawn BOS does not end generation', async t => {
  const page = await pageFor(t);
  const prompt = 'They were happy and went home. The end.';
  const prefix = await reset(page, prompt);
  await settings(page, 2, 1);
  const dist = distribution(await page.evaluate(tokens => Array.from(TinyLM.logits(tokens).at(-1)), prefix), 2, 1);
  // Choose input seeds, never output tokens: the real sampler must land there by itself.
  const seedFor = accept => { for (let seed = 0; seed < 1000000; seed++) if (accept(seed)) return seed; };
  const outsideSeed = seedFor(seed => !dist.order.slice(0, 10).includes(sample(dist, rngFrom(seed))));
  assert.notEqual(outsideSeed, undefined, 'find a real draw outside the displayed ten');
  await reset(page, prompt, outsideSeed);
  const outsideId = await step(page);
  assert.equal(outsideId, sample(dist, rngFrom(outsideSeed)));
  await chart(page, dist, outsideId);
  const bosSeed = seedFor(seed => sample(dist, rngFrom(seed)) === BOS);
  assert.notEqual(bosSeed, undefined, 'find a real seed that samples BOS');
  await reset(page, prompt, bosSeed);
  assert.equal(await step(page), BOS);
  assert.match(await chips(page).last().innerText(), /new story/i, 'BOS is shown as the start of a new story');
  await reset(page, prompt, bosSeed);
  const tokens = await run(page);
  assert.equal(tokens[prefix.length], BOS);
  assert.equal(await chips(page).count(), 40, 'BOS does not end a Run');
});
