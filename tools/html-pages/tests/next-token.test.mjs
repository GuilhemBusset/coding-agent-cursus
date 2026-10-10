import test from 'node:test';
import assert from 'node:assert/strict';
import { access, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { repoRoot, suites, eventually } from './component-helpers.mjs';

/* Locked acceptance checks for issue 38.
 * Only the public NextToken API and markup explicitly agreed in the design are
 * used. Controls are found by their accessible names, not application ids.
 * Charts are identified by their data/semantics, not DOM order. Tally nesting
 * below a prompt id is free, but token-id and raw-miss keys must retain counts.
 * Review prose is bound to the page; its quality remains a reviewer obligation.
 * No snapshots, network, model execution, or generated implementation assets.
 */
const base = 'sessions/01-fundamentals/cursus';
const file = path.join(repoRoot, base, 'labs/next-token.html');
const reviewFile = path.join(repoRoot, base, 'labs/next-token/review.md');
const fixture = JSON.parse(await readFile(path.join(repoRoot, base, 'fixtures/next_token.json'), 'utf8'));
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

async function pageFor(t, { init, javaScriptEnabled = true } = {}) {
  await access(file); // A missing deliverable fails promptly, including before browser launch.
  const browser = await chromium.launch();
  t.after(() => browser.close());
  const context = await browser.newContext({ offline: true, javaScriptEnabled, viewport: { width: 1280, height: 900 } });
  if (init) await context.addInitScript(init);
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  const requests = [], errors = [];
  page.on('request', request => requests.push(request.url()));
  page.on('pageerror', error => errors.push(error.message));
  await context.route(/^(?:https?|wss?):/i, route => route.abort());
  t.after(() => {
    assert.deepEqual(errors, [], 'no page errors');
    assert.ok(requests.length > 0, 'load was observed');
    assert.ok(requests.every(url => url.startsWith('file://')), `offline requests: ${requests.join(', ')}`);
  });
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
  const move = index > current ? next(page) : previous(page);
  for (let i = 0; i < Math.abs(index - current); i++) await move.click();
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
async function concealed(page) {
  assert.equal(await reveal(page).isEnabled(), false, 'Reveal requires a locked guess');
  const all = page.locator('ol[data-prob-chart]');
  assert.equal(await all.count(), 3);
  for (const chart of await all.all()) {
    assert.equal(await chart.isVisible(), false);
    assert.equal(await chart.evaluate(el => !!el.closest('[hidden]')), true, 'charts use hidden');
    assert.equal(await chart.ariaSnapshot(), '', 'probabilities absent from accessibility tree');
  }
  for (const name of ranges) {
    // Include hidden controls using their native range attributes; accessible
    // role lookup deliberately cannot reach them until Reveal.
    assert.equal(await slider(page, name).count(), 0, 'sampling slider absent from accessibility tree');
  }
  const snapshot = await page.locator('body').ariaSnapshot();
  assert.doesNotMatch(snapshot, /\d(?:\.\d+)?\s*%/, 'no probability before committing a guess');
  const labels = await page.locator('ol[data-prob-chart] [data-prob-label]').allTextContents();
  // Token words can legitimately occur in the prompt or teaching prose. Their
  // chart accessibility subtrees, rather than arbitrary word substrings, are hidden.
  assert.ok(labels.every(label => !snapshot.includes(`- listitem: ${label}`)));
}
async function setRange(page, name, value) {
  const input = slider(page, name);
  const bounds = await input.evaluate(el => ({ min: Number(el.min), step: Number(el.step || 1) }));
  const steps = Math.round((value - bounds.min) / bounds.step);
  close(bounds.min + steps * bounds.step, value, 1e-8, 'requested slider step');
  await input.focus();
  await input.press('Home');
  for (let i = 0; i < steps; i++) await input.press('ArrowRight');
  close(Number(await input.inputValue()), value, 1e-8, 'keyboard slider value');
  const root = input.locator('xpath=ancestor::*[@data-formula][1]');
  assert.equal(await root.count(), 1, 'range belongs to a shared formula component');
  const output = normal(await root.locator('output').innerText());
  const numbers = output.match(/\d+(?:\.\d+)?/g)?.map(Number) ?? [];
  assert.ok(numbers.some(x => Math.abs(x - value) < 1e-9), `live value ${value} in ${output}`);
  if (/temperature/i.test(name.source)) {
    assert.match(output, /exp/i);
    assert.match(output, /Σ|∑|sum/i);
    assert.match(output, /z/i);
    assert.match(output, /\/|÷/);
  }
}
async function settings(page, opts) {
  await setRange(page, ranges[0], opts.temperature);
  await setRange(page, ranges[1], opts.topK);
  await setRange(page, ranges[2], opts.topP);
}
async function chartMatches(chart, prompt, expected, nucleus = null) {
  const rows = chart.locator('li[data-value]');
  assert.equal(await rows.count(), prompt.top.length);
  vector(await values(chart), expected);
  for (let i = 0; i < prompt.top.length; i++) {
    const row = rows.nth(i);
    assert.equal(await row.isVisible(), true);
    const label = row.locator('[data-prob-label]');
    assert.ok((await label.innerText()).includes(display(prompt.top[i].text)), `render token ${i} with whitespace markers`);
    if (nucleus) {
      const kept = nucleus.includes(i);
      assert.equal(await row.evaluate(el => el.hasAttribute('data-nucleus')), kept);
      assert.match(await row.innerText(), kept ? /\bkept\b/i : /\bcut\b/i);
    }
  }
}
function section(markdown, pattern) {
  const lines = markdown.split('\n');
  const start = lines.findIndex(line => /^#{1,6} /.test(line) && pattern.test(line));
  assert.ok(start >= 0, `review section ${pattern}`);
  const level = lines[start].match(/^#+/)[0].length;
  let end = start + 1;
  while (end < lines.length && !(new RegExp(`^#{1,${level}} `)).test(lines[end])) end++;
  return lines.slice(start + 1, end).join('\n');
}
function quoteBlocks(text) {
  return [...text.matchAll(/(?:^>[^\n]*(?:\n|$))+/gm)]
    .map(m => normal(m[0].replace(/^>\s?/gm, ''))).filter(Boolean);
}

// Numeric tests include unseen vectors, unsorted logits and nontrivial boundaries.
test('A1: stable tempered softmax, limits, shift invariance, purity and invalid T', async t => {
  const page = await pageFor(t);
  for (const T of [1, 0.5]) vector(await api(page, 'softmax', [[2, 1, 0], T]), softmax([2, 1, 0], T));
  vector(await api(page, 'softmax', [[7, 7, 7, 7], 0.1]), [0.25, 0.25, 0.25, 0.25]);
  const z = [-3.75, 2.125, 0.33, 8.1, 8.09, -19];
  for (const T of [0.1, 0.35, 1.65, 2, 17]) {
    const got = await api(page, 'softmax', [z, T]);
    vector(got, softmax(z, T));
    vector(await api(page, 'softmax', [z.map(x => x + 1234), T]), got, 1e-11);
  }
  const extreme = await api(page, 'softmax', [[1000, -1000, 0], 1]);
  assert.ok(extreme.every(Number.isFinite)); close(sum(extreme), 1);
  vector(await api(page, 'softmax', [[3, 1, -1], 0.001]), [1, 0, 0]);
  vector(await api(page, 'softmax', [[3, 1, -1], 1e9]), [1 / 3, 1 / 3, 1 / 3], 1e-8);
  const result = await page.evaluate(() => {
    const z = [0.3, 8, -5, 8], before = [...z];
    NextToken.softmax(z, 0.7);
    return { before, after: z, rejected: [0, -1, NaN, Infinity, -Infinity].map(T => {
      try { NextToken.softmax([2, 1], T); return false; } catch { return true; }
    }) };
  });
  assert.deepEqual(result.after, result.before);
  assert.deepEqual(result.rejected, [true, true, true, true, true]);
});

test('A1: top-p includes crossing token, stable ties and p=1 keeps all', async t => {
  const page = await pageFor(t);
  const cases = [
    [[0.25, 0.25, 0.25, 0.25], 0.5, [0, 1]],
    [[0.25, 0.25, 0.25, 0.25], 0.500001, [0, 1, 2]],
    [[0.25, 0.25, 0.25, 0.25], 0.499999, [0, 1]],
    [[0.1, 0.4, 0.2, 0.3], 0.65, [1, 3]],
    [[0.04, 0.03, 0.9, 0.03], 0.8, [2]],
    [[1], 0.05, [0]], [[1], 1, [0]],
    [[0.3, 0.1, 0.3, 0.3], 0.6, [0, 2]],
    [[0.5, 0.5, 0, 0], 1, [0, 1, 2, 3]],
  ];
  for (const [p, threshold, expected] of cases) assert.deepEqual(await api(page, 'topP', [p, threshold]), expected);
  for (let seed = 1; seed <= 9; seed++) {
    const weights = Array.from({ length: seed + 3 }, (_, i) => ((i * 13 + seed * 7) % 29) + 1);
    const p = weights.map(x => x / sum(weights));
    for (const threshold of [0.05, 0.37, 0.8, 1]) {
      assert.deepEqual(await api(page, 'topP', [p, threshold]), prefix(p, threshold));
    }
  }
});

test('A1: composition filters top-k before nucleus and samples with exactly one RNG call', async t => {
  const page = await pageFor(t);
  for (const z of [[0, 3, 2, 1], [2.4, -8, 1, 2.4, 0.2], [1000, -1000, 0]]) {
    for (const opts of [
      { temperature: 1, topK: 2, topP: 0.7 },
      { temperature: 2, topK: z.length, topP: 0.55 },
      { temperature: 0.1, topK: 1, topP: 1 },
      { temperature: 0.75, topK: z.length, topP: 1 },
    ]) {
      const want = distribution(z, opts), got = await api(page, 'distribution', [z, opts]);
      vector(got.p, want.p); vector(got.q, want.q);
      assert.deepEqual(got.kept, want.kept); close(sum(got.q), 1);
    }
  }
  const q = [0, 0.125, 0.375, 0, 0.5, 0];
  for (const u of [0, 0.124999, 0.125, 0.499999, 0.5, 0.999999]) {
    const result = await page.evaluate(({ q, u }) => {
      let calls = 0;
      const selected = NextToken.sample(q, () => { calls++; return u; });
      return { selected, calls };
    }, { q, u });
    assert.equal(result.calls, 1); assert.equal(result.selected, inverseCDF(q, u));
  }
  for (const q of [[0.1, 0.2, 0.7], [0, 1, 0], [0.8, 0.15, 0.05]]) {
    assert.equal(await page.evaluate(q => NextToken.argmax(q), q), q.indexOf(Math.max(...q)));
  }
});

test('D1: lab contract, public API, suite registration and hash-bound screenshot review', async t => {
  const page = await pageFor(t);
  assert.equal(await page.locator('html').getAttribute('data-design-system'), 'cursus');
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'lab');
  assert.equal(await page.locator('script[type="module"]').count(), 0);
  const reserved = await page.locator('*').evaluateAll(nodes => nodes.flatMap(el => [...el.attributes]
    .filter(a => /^data-(?:lab$|reset$|budget)/.test(a.name)).map(a => a.name)));
  assert.deepEqual(reserved, []);
  assert.deepEqual(await page.evaluate(() => ['softmax', 'topP', 'distribution', 'sample', 'argmax']
    .map(name => typeof window.NextToken?.[name])), Array(5).fill('function'));
  assert.ok(suites.includes('next-token'));
  const pkg = JSON.parse(await readFile(path.join(repoRoot, 'setup/package.json'), 'utf8'));
  assert.ok(pkg.scripts.test.split(/\s+/).includes('../tools/html-pages/tests/next-token.test.mjs'));
  const bytes = await readFile(file), review = await readFile(reviewFile, 'utf8');
  assert.ok(review.includes(createHash('sha256').update(bytes).digest('hex')), 'review tied to final page');
  assert.match(review.replace(/(?<=\d),(?=\d)/g, ''), new RegExp(`\\b${bytes.length}\\s+bytes\\b`, 'i'));
  const screenshots = section(review, /screenshot/i);
  for (const view of [/desktop/i, /laptop/i, /mobile/i, /no[ -]?(?:js|javascript)/i,
    /print/i, /reduced[ -]motion/i, /revealed/i, /sampled/i]) assert.match(screenshots, view);
});

test('D2: exact fixture embedding and visible provenance', async t => {
  const page = await pageFor(t);
  assert.equal(await page.locator('#next-token-data[type="application/json"]').count(), 1);
  assert.deepEqual(JSON.parse(await page.locator('#next-token-data').textContent()), fixture);
  const footer = page.locator('footer');
  assert.equal(await footer.isVisible(), true);
  const text = await footer.innerText();
  for (const model of fixture.meta.models) {
    assert.ok(text.includes(model.id)); assert.ok(text.includes(model.revision));
  }
  for (const value of [fixture.meta.date, fixture.meta.generator, ...Object.keys(fixture.meta.libraries),
    ...Object.values(fixture.meta.libraries)]) assert.ok(text.includes(value), `provenance ${value}`);
});

test('D2: every prompt gates its real full-vocabulary chart; carousel travels in both directions', async t => {
  const page = await pageFor(t);
  for (let index = 0; index < prompts.length; index++) {
    if (index) await next(page).click();
    await visit(page, index, index);
    await concealed(page);
    const prompt = prompts[index];
    await lockedGuess(page, display(prompt.top[0].text));
    // Locking does not reveal any probability; only Reveal does.
    for (const chart of await page.locator('ol[data-prob-chart]').all()) assert.equal(await chart.isVisible(), false);
    await reveal(page).click();
    assert.equal(await guessInput(page).isEnabled(), false);
    const { recorded, sampling } = await charts(page, prompt);
    assert.equal(await sampling.isVisible(), true);
    const want = prompt.top.map(token => Math.exp(token.logit - prompt.logsumexp));
    const rows = recorded.locator('li[data-value]');
    assert.ok([prompt.top.length, prompt.top.length + 1].includes(await rows.count()));
    vector((await values(recorded)).slice(0, prompt.top.length), want, 1e-6);
    for (let i = 0; i < prompt.top.length; i++) {
      assert.equal(await rows.nth(i).isVisible(), true);
      assert.ok((await rows.nth(i).locator('[data-prob-label]').innerText()).includes(display(prompt.top[i].text)));
    }
    const others = page.getByText(/(?:all\s+)?other tokens/i).filter({ visible: true });
    assert.ok(await others.count() > 0, 'remaining full-vocabulary mass is shown');
    const otherMass = await others.first().evaluate(el => {
      const row = el.closest('[data-value]');
      if (row) return { exact: Number(row.dataset.value) };
      // A readout may be inline text or a labelled output beside the label.
      const own = el.innerText;
      return { text: /\d/.test(own) ? own : el.parentElement.innerText };
    });
    if ('exact' in otherMass) close(otherMass.exact, 1 - sum(want), 1e-6);
    else {
      const percentages = [...otherMass.text.matchAll(/(\d+(?:\.\d+)?)\s*%/g)].map(m => Number(m[1]) / 100);
      assert.ok(percentages.some(p => Math.abs(p - (1 - sum(want))) <= 0.0051), 'other-token mass readout');
    }
    const body = await page.locator('body').innerText();
    const coverage = [...body.matchAll(/(\d+(?:\.\d+)?)\s*%/g)].map(m => Number(m[1]) / 100);
    assert.ok(coverage.some(p => Math.abs(p - sum(want)) <= 0.0051), 'top-20 full-vocabulary coverage percentage');
  }
  for (let index = prompts.length - 2; index >= 0; index--) {
    await previous(page).click();
    await visit(page, index, index);
    await concealed(page);
  }
});

// Find a compact visible feedback block through its content, without prescribing
// a result id, tag, or component. Charts and input values are not feedback.
async function feedback(page, guess) {
  return page.locator('body').evaluate((body, guess) => {
    const candidates = [...body.querySelectorAll('*')].filter(el => {
      if (el.closest('ol[data-prob-chart], footer, script, style') || !el.getClientRects().length) return false;
      const text = el.innerText || '';
      if (/total\s*(?:guesses|bets)/i.test(text) && /top\s*5/i.test(text)) return false;
      return text.includes(guess) && /\brank\s*#?\s*\d+|#\d+|not in (?:the )?top\s*20/i.test(text);
    });
    // Multiple trimmed matches may occupy separate rows. Retain the smallest
    // matching blocks, so an enclosing page/container cannot supply fake ranks.
    const leaves = candidates.filter(el => !candidates.some(other => other !== el && el.contains(other)));
    return leaves.map(el => el.innerText).join('\n');
  }, guess);
}
function ranksIn(text) {
  return [...text.matchAll(/\brank\s*#?\s*(\d+)|#(\d+)/gi)].map(m => Number(m[1] ?? m[2]));
}

test('D2: guesses prioritize exact whitespace, preserve ambiguous ranks and accept newline notation', async t => {
  const page = await pageFor(t);
  const cases = [];
  for (const [id, exact] of [['idiom-thanks', 'much'], ['code-return', '+']]) {
    const index = prompts.findIndex(p => p.id === id);
    assert.ok(index >= 0, `fixture witness ${id}`);
    const prompt = prompts[index];
    const exactRank = prompt.top.findIndex(token => token.text === exact) + 1;
    const spacedRank = prompt.top.findIndex(token => token.text === ` ${exact}`) + 1;
    assert.ok(exactRank > 0 && spacedRank > 0);
    cases.push({ index, guess: exact, ranks: [exactRank] });
    cases.push({ index, guess: `␣${exact}`, ranks: [spacedRank] });
    cases.push({ index, guess: `  ${exact}  `, ranks: [spacedRank, exactRank], ambiguous: true });
  }
  const newlineIndex = prompts.findIndex(p => p.top.some(token => token.text === '\n'));
  assert.ok(newlineIndex >= 0);
  const newlineRank = prompts[newlineIndex].top.findIndex(token => token.text === '\n') + 1;
  cases.push({ index: newlineIndex, guess: '↵', ranks: [newlineRank] });
  cases.push({ index: newlineIndex, guess: '\\n', ranks: [newlineRank] });
  cases.push({ index: 0, guess: 'zz_unlisted_class_bet_7391', ranks: [] });
  for (const item of cases) {
    await page.reload();
    await visit(page, item.index);
    await lockedGuess(page, item.guess);
    await reveal(page).click();
    // A literal \n may be rendered as the documented ↵ marker in the lock log.
    const shown = item.guess === '\\n' ? '↵' : item.guess.trim();
    let result = await feedback(page, shown);
    if (!result && item.guess === '\\n') result = await feedback(page, item.guess);
    assert.ok(result, `feedback for ${JSON.stringify(item.guess)}`);
    if (!item.ranks.length) assert.match(result, /not in (?:the )?top\s*20/i);
    else {
      assert.deepEqual([...new Set(ranksIn(result))].sort((a, b) => a - b), [...item.ranks].sort((a, b) => a - b),
        `rank feedback for ${JSON.stringify(item.guess)}: ${result}`);
      if (item.ambiguous) {
        for (const rank of item.ranks) {
          const token = display(prompts[item.index].top[rank - 1].text);
          assert.ok(result.includes(token), `ambiguous feedback identifies ${token}`);
        }
      }
    }
  }
});

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
async function tallyText(page) {
  return page.locator('body').evaluate(body => {
    const candidates = [...body.querySelectorAll('*')].filter(el => el.getClientRects().length &&
      /total\s*(?:locked\s*)?(?:guesses|bets)|(?:guesses|bets)\s*total/i.test(el.innerText || '') &&
      /top\s*5|top\s*five/i.test(el.innerText || ''));
    candidates.sort((a, b) => a.innerText.length - b.innerText.length);
    return candidates[0]?.innerText ?? '';
  });
}
function metric(text, label, expected) {
  const pattern = new RegExp(`(?:${label.source})[^\\d\\n]{0,30}(\\d+)|(\\d+)[^\\d\\n]{0,20}(?:${label.source})`, 'i');
  const match = text.match(pattern);
  assert.ok(match, `visible tally metric ${label}: ${text}`);
  assert.equal(Number(match[1] ?? match[2]), expected, `tally metric ${label}`);
}

test('D2: immutable multiple locks, token-id tally, misses, reload persistence and Reset tally', async t => {
  const page = await pageFor(t);
  const prompt = prompts[0], miss = 'unlisted raw miss 7391';
  for (const raw of [display(prompt.top[0].text), display(prompt.top[0].text), display(prompt.top[6].text), miss]) {
    await lockedGuess(page, raw);
  }
  const state = await tally(page), record = findKey(state, prompt.id);
  assert.ok(record, 'prompt-id tally bucket');
  assert.equal(storedCount(findKey(record, String(prompt.top[0].id))), 2);
  assert.equal(storedCount(findKey(record, String(prompt.top[6].id))), 1);
  const misses = findKey(record, 'miss');
  assert.ok(misses, 'miss bucket');
  assert.equal(storedCount(findKey(misses, miss)), 1, 'raw guess text keys the miss');
  await reveal(page).click();
  assert.equal(await guessInput(page).isEnabled(), false);
  // An editable control outside the now-disabled entry must not expose prior bets.
  const editable = await page.locator('input:not(:disabled), textarea:not(:disabled), [contenteditable="true"]').evaluateAll(nodes =>
    nodes.filter(el => el.getClientRects().length).map(el => el.value ?? el.textContent));
  assert.ok(!editable.includes(miss));
  assert.match(await feedback(page, miss), /not in (?:the )?top\s*20/i);
  const summary = await tallyText(page);
  metric(summary, /total\s*(?:locked\s*)?(?:guesses|bets)|(?:guesses|bets)\s*total/, 4);
  metric(summary, /(?:hits?\s*(?:at\s*)?)?rank\s*1|top\s*1/, 2);
  metric(summary, /(?:hits?\s*(?:in\s*)?(?:the\s*)?)?top\s*5/, 2);
  const common = await page.locator('body').evaluate((body, token) => {
    const candidates = [...body.querySelectorAll('*')].filter(el => el.getClientRects().length &&
      !el.querySelector('ol[data-prob-chart]') && /most common|popular|frequen/i.test(el.innerText || '') &&
      (el.innerText || '').includes(token));
    candidates.sort((a, b) => a.innerText.length - b.innerText.length);
    return candidates[0]?.innerText ?? '';
  }, display(prompt.top[0].text));
  assert.ok(common, 'most common guesses name the repeated token');
  assert.match(common, /\b2\b/, 'most common guess displays its count');
  await page.reload();
  assert.deepEqual(await tally(page), state, 'reload retains tally without double counting');
  await next(page).click();
  await lockedGuess(page, display(prompts[1].top[1].text));
  const second = await tally(page);
  assert.deepEqual(findKey(second, prompt.id), record, 'separate prompt buckets');
  assert.equal(storedCount(findKey(findKey(second, prompts[1].id), String(prompts[1].top[1].id))), 1);
  await page.getByRole('button', { name: /reset tally/i }).click();
  const cleared = await tally(page);
  for (const p of [prompt, prompts[1]]) {
    const bucket = findKey(cleared, p.id);
    assert.ok(bucket === undefined || !JSON.stringify(bucket).match(/:\s*[1-9]\d*(?:[,}])/), 'Reset removes counts');
  }
  await page.reload();
  const resetSummary = await tallyText(page);
  metric(resetSummary, /total\s*(?:locked\s*)?(?:guesses|bets)|(?:guesses|bets)\s*total/, 0);
});

test('D2: corrupt storage recovers and unavailable storage uses a disclosed working memory tally', async t => {
  const corrupt = await pageFor(t, { init: () => localStorage.setItem('cursus-s1-next-token-tally-v1', '{broken json') });
  await lockedGuess(corrupt, display(prompts[0].top[0].text));
  const saved = findKey(await tally(corrupt), prompts[0].id);
  assert.equal(storedCount(findKey(saved, String(prompts[0].top[0].id))), 1);
  const unavailable = await pageFor(t, { init: () => {
    Object.defineProperty(window, 'localStorage', { configurable: true, get() { throw new Error('storage unavailable'); } });
  } });
  const text = await unavailable.locator('body').innerText();
  assert.match(text, /memory|not (?:be )?saved|cannot (?:be )?save|storage.*unavailable/i);
  await lockedGuess(unavailable, display(prompts[0].top[0].text));
  await reveal(unavailable).click();
  metric(await tallyText(unavailable), /total\s*(?:locked\s*)?(?:guesses|bets)|(?:guesses|bets)\s*total/, 1);
  await unavailable.getByRole('button', { name: /reset tally/i }).click();
  metric(await tallyText(unavailable), /total\s*(?:locked\s*)?(?:guesses|bets)|(?:guesses|bets)\s*total/, 0);
});

test('D3: real slider controls update q, formula values and the labelled nucleus across prompts and limits', async t => {
  const page = await pageFor(t);
  const indices = [...new Set([0, Math.floor(prompts.length / 2), prompts.findIndex(p => p.id === 'code-return')])];
  for (const index of indices) {
    await page.reload();
    await revealPrompt(page, index);
    const prompt = prompts[index], n = prompt.top.length;
    const { sampling } = await charts(page, prompt);
    for (const [i, min, max, step, value] of [[0, 0.1, 2, 0.05, 1], [1, 1, n, 1, n], [2, 0.05, 1, 0.05, 1]]) {
      const input = slider(page, ranges[i]);
      assert.equal(Number(await input.getAttribute('min')), min);
      assert.equal(Number(await input.getAttribute('max')), max);
      assert.equal(Number((await input.getAttribute('step')) ?? 1), step);
      assert.equal(Number(await input.inputValue()), value);
    }
    for (const opts of [
      { temperature: 1, topK: n, topP: 1 },
      { temperature: 0.1, topK: 1, topP: 0.05 },
      { temperature: 2, topK: n, topP: 1 },
      { temperature: 0.65, topK: 7, topP: 0.75 },
      { temperature: 1.85, topK: 3, topP: 0.55 },
    ]) {
      await settings(page, opts);
      const expected = distribution(prompt.top.map(token => token.logit), opts);
      await eventually(() => chartMatches(sampling, prompt, expected.q, expected.kept));
      // Count and retained pre-filter mass must be a readout, not just shading.
      const body = await page.locator('body').innerText();
      assert.match(body, new RegExp(`(?:kept|keep|nucleus)[^\\n\\d]{0,25}${expected.kept.length}\\b|\\b${expected.kept.length}[^\\n\\d]{0,25}(?:kept|retained|candidates)`, 'i'));
      const massValues = [...body.matchAll(/(\d+(?:\.\d+)?)\s*%/g)].map(m => Number(m[1]) / 100);
      assert.ok(massValues.some(x => Math.abs(x - expected.mass) <= 0.0051), 'pre-filter retained mass is shown');
    }
  }
});

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

test('D3/A2: injected random sequence gives exact batch counts; Argmax, replacement and invalidation', async t => {
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
  const radios = page.getByRole('radio');
  assert.equal(await radios.count(), 2);
  const sampleMode = page.getByRole('radio', { name: /^sample$/i });
  const argmaxMode = page.getByRole('radio', { name: /argmax/i });
  assert.equal(await sampleMode.evaluate(el => el.tagName === 'INPUT' && el.type === 'radio'), true);
  assert.equal(await argmaxMode.getAttribute('name'), await sampleMode.getAttribute('name'));
  assert.ok(await sampleMode.getAttribute('name'));
  const group = page.getByRole('group', { name: /decod/i }).or(page.getByRole('radiogroup', { name: /decod/i }));
  assert.equal(await group.count(), 1, 'named decoding group');
  await sampleMode.check();
  const expectedCounts = Array(prompt.top.length).fill(0);
  for (let i = 0; i < 100; i++) expectedCounts[inverseCDF(want.q, (i + 0.5) / 100)]++;
  for (let batchIndex = 0; batchIndex < 2; batchIndex++) {
    const before = await page.evaluate(() => window.__nextTokenTestDraws);
    await batch(page).click();
    assert.equal(await page.evaluate(() => window.__nextTokenTestDraws), before + 100);
    await eventually(() => histogramMatches(histogram, prompt, expectedCounts));
    close(sum(await values(histogram)), 1);
  }
  await argmaxMode.check();
  const before = await page.evaluate(() => window.__nextTokenTestDraws);
  await batch(page).click();
  const greedy = Array(prompt.top.length).fill(0);
  greedy[want.q.indexOf(Math.max(...want.q))] = 100;
  await histogramMatches(histogram, prompt, greedy);
  assert.equal(await page.evaluate(() => window.__nextTokenTestDraws), before, 'Argmax consumes no randomness');
  for (const [name, value] of [[ranges[0], 1.5], [ranges[1], 8], [ranges[2], 0.8]]) {
    await setRange(page, name, value);
    await histogramEmpty(histogram);
    await batch(page).click();
    close(sum(await values(histogram)), 1);
  }
  await next(page).click();
  await concealed(page);
  await histogramEmpty(histogram);
  const scripts = await page.locator('script:not([type="application/json"])').allTextContents();
  for (const script of scripts) assert.doesNotMatch(script,
    /\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|\bimport\s*\(|\bnew\s+(?:Shared)?Worker\b/);
});

test('D3: visible explanatory prose is quoted and assessed in the final-page review', async t => {
  const page = await pageFor(t);
  await revealPrompt(page);
  const text = normal(await page.locator('body').innerText());
  const review = await readFile(reviewFile, 'utf8');
  const prose = section(review, /prose/i);
  const blocks = quoteBlocks(prose);
  for (const quote of blocks) assert.ok(text.includes(quote), `review quote appears verbatim in visible page text: ${quote}`);
  // Quotes may use blockquotes, inline quotation marks, or copied paragraphs.
  // Match rendered paragraphs too, without prescribing review Markdown style.
  const paragraphs = await page.locator('p, figcaption, aside').evaluateAll(nodes => nodes
    .filter(el => el.getClientRects().length).map(el => el.innerText));
  const quotes = [...new Set([...blocks, ...paragraphs.map(normal)
    .filter(p => p.length > 30 && normal(prose).includes(p))])];
  assert.ok(quotes.some(q => /random|reproduc/i.test(q)), 'verbatim reproducibility quote');
  assert.ok(quotes.some(q => /sandbox|top[ -]20|full[ -]vocabulary/i.test(q)), 'verbatim sandbox/coverage quote');
  // The assessment must be separate prose, not just headings and quoted copy.
  let assessment = normal(prose.replace(/^#+[^\n]*$/gm, ''));
  for (const quote of quotes.sort((a, b) => b.length - a.length)) assessment = assessment.replace(quote, '');
  assert.ok(assessment.split(/\s+/).filter(word => /[a-z]{2}/i.test(word)).length >= 12, 'written prose assessment');
  assert.match(text, /simulated draws from the probabilities above/i);
});

test('D2/A2: no-JavaScript view explains why the carousel cannot run', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  assert.match(await page.locator('body').innerText(), /(?:carousel|lab|guesses|prompts)[^.\n]*JavaScript|JavaScript[^.\n]*(?:carousel|lab|guesses|prompts)/i);
});
