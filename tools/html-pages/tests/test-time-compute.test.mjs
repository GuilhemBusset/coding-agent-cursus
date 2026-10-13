import test from 'node:test';
import assert from 'node:assert/strict';
import { access, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { repoRoot, suites, eventually, initialPredict } from './component-helpers.mjs';

/* Locked acceptance contract for issue 31. Expected numbers are computed here,
 * never by calling the page's API. Only the agreed API, geometry and data-*
 * selectors are contractual; range controls are identified by their public
 * bounds/defaults, not private ids or extra naming conventions.
 *
 * PARAMS.effort.inverse.ceil is the sigmoid's upper asymptote (0.8 in the
 * recommended model): floor + (ceil-floor)*sigmoid - lambda*hinge.
 * The design's sentence that majority rises at every finite N is not generally
 * true. The beta-binomial majority rule, including half credit for ties, is the
 * mathematical contract; only coverage is required to be monotone in N.
 * Prose/citation accuracy and screenshot inspection remain named, hash-bound
 * review evidence. These checks do not claim to automate those judgments.
 */
const stem = 'sessions/01-fundamentals/cursus/labs/test-time-compute';
const file = path.join(repoRoot, `${stem}.html`);
const reviewFile = path.join(repoRoot, stem, 'review.md');
const panelIds = ['best-of-n', 'effort-dial', 'sharpen-or-expand'];
const sources = [['2407.21787'], ['2408.03314', '2507.14417'], ['2504.13837']];
const panel = (page, id) => page.locator(`section[data-panel]#${id}`);
const normal = s => s.replace(/\s+/g, ' ').trim();
const mathText = s => s.replace(/[−–—]/g, '-').replace(/½/g, '1/2').replace(/\s+/g, '');
const sum = xs => xs.reduce((a, b) => a + b, 0);
const sigmoid = x => 1 / (1 + Math.exp(-x));

function near(actual, expected, tolerance = 1e-9, label = 'value') {
  assert.ok(Number.isFinite(actual) && Number.isFinite(expected), `${label}: finite (${actual}, ${expected})`);
  assert.ok(Math.abs(actual - expected) <= tolerance,
    `${label}: ${actual} != ${expected}, tolerance ${tolerance}`);
}
function probability(value, label) {
  assert.ok(Number.isFinite(value) && value >= -1e-12 && value <= 1 + 1e-12, `${label}: probability ${value}`);
}

// Direct product is independent of the required log-space page implementation.
function passOracle(a, b, n) {
  let failure = 1;
  for (let j = 0; j < n; j++) failure *= (b + j) / (a + b + j);
  return 1 - failure;
}
function mixtureOracle(components, k) {
  return sum(components.map(c => c.w * passOracle(c.a, c.b, k)));
}
// Beta-binomial recurrence, rather than a page helper or log-gamma library.
function betaBinomial(a, b, n) {
  // Keep P(0) itself: subtracting a near-one coverage loses this tiny anchor.
  let p0 = 1;
  for (let j = 0; j < n; j++) p0 *= (b + j) / (a + b + j);
  const pmf = [p0];
  for (let k = 0; k < n; k++)
    pmf.push(pmf[k] * (n - k) / (k + 1) * (a + k) / (b + n - k - 1));
  near(sum(pmf), 1, 2e-9, 'oracle beta-binomial normalization');
  return pmf;
}
// Start at the mode and normalize ratios: no underflowing (1-f)^1024 anchor.
function binomial(n, f) {
  const pmf = Array(n + 1).fill(0);
  if (f === 0 || f === 1) { pmf[f === 0 ? 0 : n] = 1; return pmf; }
  const mode = Math.min(n, Math.floor((n + 1) * f));
  pmf[mode] = 1;
  for (let w = mode; w < n; w++) pmf[w + 1] = pmf[w] * (n - w) / (w + 1) * f / (1 - f);
  for (let w = mode; w > 0; w--) pmf[w - 1] = pmf[w] * w / (n - w + 1) * (1 - f) / f;
  const mass = sum(pmf);
  return pmf.map(p => p / mass);
}
const oracleCache = new Map();
function bestOracle(a, b, n, f) {
  const key = [a, b, n, f].join('/');
  if (oracleCache.has(key)) return oracleCache.get(key);
  const pmf = betaBinomial(a, b, n);
  const coverage = sum(pmf.slice(1));
  const majority = sum(pmf.filter((_, k) => k > n / 2)) + (n % 2 === 0 ? pmf[n / 2] / 2 : 0);
  let verifier = 0;
  // K=0 contributes zero, including the empty accepted set.
  for (let k = 1; k <= n; k++) {
    const wrongAccepted = binomial(n - k, f);
    verifier += pmf[k] * sum(wrongAccepted.map((p, w) => p * k / (k + w)));
  }
  const result = { coverage, majority, verifier };
  oracleCache.set(key, result);
  return result;
}
function effortOracle(params, x, id) {
  const d = params.difficulties.find(d => d.id === id);
  assert.ok(d, `disclosed difficulty ${id}`);
  return params.floor + (d.ceil - params.floor) * sigmoid(params.slope * (x - d.mid));
}
function inverseOracle(params, x) {
  const d = params.inverse;
  return params.floor + (d.ceil - params.floor) * sigmoid(params.slope * (x - d.mid)) -
    d.lambda * Math.max(0, x - d.peak);
}
function midpointOracle(a, b, n, steps = 100000) {
  let mass = 0, solved = 0;
  for (let i = 0; i < steps; i++) {
    const p = (i + 0.5) / steps;
    const density = p ** (a - 1) * (1 - p) ** (b - 1);
    mass += density;
    solved += density * (-Math.expm1(n * Math.log1p(-p)));
  }
  return solved / mass;
}
function mulberry32(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6D2B79F5) >>> 0;
    let v = Math.imul(state ^ (state >>> 15), state | 1);
    v ^= v + Math.imul(v ^ (v >>> 7), v | 61);
    return ((v ^ (v >>> 14)) >>> 0) / 4294967296;
  };
}
function gamma(shape, rng) {
  const positiveUniform = () => Math.max(Number.MIN_VALUE, rng());
  if (shape < 1) return gamma(shape + 1, rng) * positiveUniform() ** (1 / shape);
  const d = shape - 1 / 3, c = 1 / Math.sqrt(9 * d);
  for (;;) {
    const z = Math.sqrt(-2 * Math.log(positiveUniform())) * Math.cos(2 * Math.PI * rng());
    const root = 1 + c * z;
    if (root <= 0) continue;
    const v = root ** 3, u = positiveUniform();
    if (u < 1 - 0.0331 * z ** 4 || Math.log(u) < z * z / 2 + d * (1 - v + Math.log(v))) return d * v;
  }
}
function monteCarlo(a, b, ns, seed) {
  const rng = mulberry32(seed), estimates = ns.map(() => 0), draws = 200000;
  for (let i = 0; i < draws; i++) {
    const x = gamma(a, rng), y = gamma(b, rng), p = x / (x + y);
    ns.forEach((n, j) => { estimates[j] += -Math.expm1(n * Math.log1p(-p)); });
  }
  return estimates.map(x => x / draws);
}

async function pageFor(t, { javaScriptEnabled = true, viewport = { width: 1280, height: 900 }, reducedMotion } = {}) {
  await access(file); // Fail before browser launch when the deliverable is missing.
  const browser = await chromium.launch();
  const errors = [], requests = [];
  t.after(async () => {
    await browser.close();
    assert.deepEqual(errors, [], 'no browser errors');
    assert.ok(requests.length > 0, 'observed file load');
    assert.ok(requests.every(url => url.startsWith('file://')), `self-contained offline requests: ${requests.join(', ')}`);
  });
  const context = await browser.newContext({ offline: true, javaScriptEnabled, viewport, ...(reducedMotion ? { reducedMotion } : {}) });
  await context.route(/^(?:https?|wss?|ftp):/i, route => {
    errors.push(`remote request: ${route.request().url()}`);
    return route.abort();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => requests.push(r.url()));
  page.on('websocket', socket => errors.push(`websocket: ${socket.url()}`));
  await page.goto(pathToFileURL(file).href);
  return page;
}
const api = (page, method, args = []) => page.evaluate(({ method, args }) => window.TestTimeCompute[method](...args), { method, args });
const paramsFor = page => page.evaluate(() => window.TestTimeCompute.PARAMS);

async function rangeContract(input, min, max, step, value) {
  assert.equal(await input.count(), 1, 'one native range');
  assert.equal(await input.getAttribute('type'), 'range');
  assert.equal(await input.isEnabled(), true, 'range is operable');
  for (const [key, expected] of Object.entries({ min, max, step })) near(Number(await input.getAttribute(key)), expected, 1e-12, key);
  near(Number(await input.inputValue()), value, 1e-12, 'default selection');
}
async function bestControls(root) {
  const ranges = root.locator('input[type=range]');
  assert.equal(await ranges.count(), 4, 'a, b, fpr, log2N controls');
  const data = await ranges.evaluateAll(nodes => nodes.map(n => ({ min: Number(n.min), max: Number(n.max), value: Number(n.value) })));
  const find = predicate => {
    const indices = data.flatMap((d, i) => predicate(d) ? [i] : []);
    assert.equal(indices.length, 1, 'uniquely identifiable range');
    return ranges.nth(indices[0]);
  };
  const controls = {
    a: find(d => d.min === 0.2 && d.max === 5 && d.value === 0.6),
    b: find(d => d.min === 0.2 && d.max === 5 && d.value === 2.4),
    f: find(d => d.min === 0 && d.max === 1),
    q: find(d => d.min === 0 && d.max === 10),
  };
  await rangeContract(controls.a, 0.2, 5, 0.1, 0.6);
  await rangeContract(controls.b, 0.2, 5, 0.1, 2.4);
  await rangeContract(controls.f, 0, 1, 0.05, 0.1);
  await rangeContract(controls.q, 0, 10, 1, 4);
  return controls;
}
async function setRange(input, value) {
  const min = Number(await input.getAttribute('min')), max = Number(await input.getAttribute('max'));
  const step = Number(await input.getAttribute('step'));
  assert.ok(value >= min && value <= max);
  if (Math.abs(Number(await input.inputValue()) - value) < 1e-10) return;
  await input.focus();
  // Real keyboard input exercises event wiring and native accessibility.
  const fromLow = Math.round((value - min) / step), fromHigh = Math.round((max - value) / step);
  await input.press(fromLow <= fromHigh ? 'Home' : 'End');
  for (let i = 0; i < Math.min(fromLow, fromHigh); i++) await input.press(fromLow <= fromHigh ? 'ArrowRight' : 'ArrowLeft');
  near(Number(await input.inputValue()), value, 1e-10, 'keyboard selection');
}
async function setBest(controls, { a, b, f, q }) {
  for (const [key, value] of Object.entries({ a, b, f, q })) await setRange(controls[key], value);
}
async function percent(root, name, expected) {
  const metric = root.locator(`output[data-ttc-readout] span[data-metric="${name}"]`);
  assert.equal(await metric.count(), 1, `one ${name} readout`);
  assert.equal(await metric.isVisible(), true, `${name} readout visible`);
  const text = (await metric.innerText()).trim();
  assert.match(text, /^\d+\.\d\s*%$/, `${name}: percentage with one decimal`);
  near(Number(text.replace('%', '').trim()) / 100, expected, 0.00051, `${name} readout`);
}
async function integerMetric(root, name, expected) {
  const metric = root.locator(`output[data-ttc-readout] span[data-metric="${name}"]`);
  assert.equal(await metric.count(), 1);
  assert.equal(await metric.isVisible(), true);
  const text = (await metric.innerText()).replace(/[,\s]/g, '');
  assert.match(text, /^\d+$/);
  assert.equal(Number(text), expected, name);
}
function money(text, requireSymbol = true) {
  const normalized = text.replace(/,/g, '').trim();
  const match = normalized.match(/\$\s*(\d+(?:\.\d+)?(?:e[-+]?\d+)?)|(\d+(?:\.\d+)?(?:e[-+]?\d+)?)\s*\$/i);
  // Axis units may live in the axis title; the cost readout includes dollars.
  if (!requireSymbol && !match && /^\d+(?:\.\d+)?(?:e[-+]?\d+)?$/i.test(normalized)) return Number(normalized);
  assert.ok(match, `illustrative dollar value: ${text}`);
  return Number(match[1] ?? match[2]);
}
async function costMetric(root, expected) {
  const metric = root.locator('output[data-ttc-readout] span[data-metric="cost"]');
  assert.equal(await metric.count(), 1);
  assert.equal(await metric.isVisible(), true);
  const value = money(await metric.innerText());
  near(value, expected, Math.max(1e-7, expected * 0.02), 'cost readout');
  return value;
}

async function chartState(root) {
  const svg = root.locator('figure[data-ttc-chart] > svg');
  assert.equal(await svg.count(), 1);
  assert.equal(await svg.getAttribute('role'), 'img');
  assert.ok(normal((await svg.getAttribute('aria-label')) ?? ''), 'named chart');
  return svg.evaluate(svg => {
    const rects = svg.querySelectorAll('rect[data-plot-area]');
    if (rects.length !== 1) throw new Error('one declared plot area');
    const r = rects[0], area = { x: r.x.baseVal.value, y: r.y.baseVal.value, width: r.width.baseVal.value, height: r.height.baseVal.value };
    const bounds = { xMin: Number(svg.dataset.xMin), xMax: Number(svg.dataset.xMax), yMin: Number(svg.dataset.yMin), yMax: Number(svg.dataset.yMax) };
    const series = Array.from(svg.querySelectorAll('polyline[data-series]'), line => ({
      id: line.dataset.series, dash: getComputedStyle(line).strokeDasharray,
      painted: getComputedStyle(line).stroke !== 'none' && parseFloat(getComputedStyle(line).strokeWidth) > 0 &&
        parseFloat(getComputedStyle(line).strokeOpacity) > 0 && parseFloat(getComputedStyle(line).opacity) > 0 &&
        getComputedStyle(line).visibility !== 'hidden' && getComputedStyle(line).display !== 'none',
      vertices: Array.from(line.points, point => ({
        x: bounds.xMin + (point.x - area.x) / area.width * (bounds.xMax - bounds.xMin),
        y: bounds.yMin + (1 - (point.y - area.y) / area.height) * (bounds.yMax - bounds.yMin),
      })),
    }));
    const xOf = node => {
      if (node.tagName.toLowerCase() === 'circle') return [node.cx.baseVal.value];
      if (node.tagName.toLowerCase() === 'line') return [node.x1.baseVal.value, node.x2.baseVal.value];
      throw new Error('selection/crossing markers must be circles or lines');
    };
    const invertX = x => bounds.xMin + (x - area.x) / area.width * (bounds.xMax - bounds.xMin);
    return { area, bounds, series, viewBox: { width: svg.viewBox.baseVal.width, height: svg.viewBox.baseVal.height },
      markers: Array.from(svg.querySelectorAll('[data-marker]'), node => xOf(node).map(invertX)),
      crossings: Array.from(svg.querySelectorAll('[data-crossing]'), node => ({ tag: node.tagName.toLowerCase(), xs: xOf(node).map(invertX),
        height: node.tagName.toLowerCase() === 'line' ? Math.abs(node.y2.baseVal.value - node.y1.baseVal.value) : 0 })),
    };
  });
}
function chartContract(state, ids, xMin, xMax, selected) {
  assert.deepEqual(state.series.map(s => s.id).sort(), [...ids].sort(), 'exact series set');
  state.series.forEach(s => assert.ok(s.painted, `${s.id}: visible stroked curve`));
  for (const [key, value] of Object.entries({ xMin, xMax, yMin: 0, yMax: 1 })) near(state.bounds[key], value, 1e-12, key);
  for (const value of Object.values(state.area)) assert.ok(Number.isFinite(value));
  assert.ok(state.area.width > 0 && state.area.height > 0, 'positive plot area');
  assert.ok(state.area.x >= 0 && state.area.y >= 0);
  assert.ok(state.area.x + state.area.width <= state.viewBox.width + 0.1);
  assert.ok(state.area.y + state.area.height <= state.viewBox.height + 0.1);
  assert.ok(state.markers.length > 0, 'current-selection marker');
  state.markers.flat().forEach(x => near(x, selected, 0.005, 'selection marker'));
}
function gridSeries(state, id, oracle, { min = 0, max = 10, integer = true } = {}) {
  const series = state.series.find(s => s.id === id);
  assert.ok(series, `${id} series`);
  if (integer) assert.equal(series.vertices.length, max - min + 1, `${id}: integer log2 grid`);
  else assert.ok(series.vertices.length >= max - min + 1, `${id}: full effort grid`);
  near(series.vertices[0].x, min, 0.001, 'first vertex');
  near(series.vertices.at(-1).x, max, 0.001, 'last vertex');
  series.vertices.forEach((v, i) => {
    if (integer) near(v.x, min + i, 0.001, `${id} grid x`);
    if (i > 0) assert.ok(v.x > series.vertices[i - 1].x, `${id}: increasing x`);
    probability(v.y, `${id} vertex`);
    near(v.y, oracle(v.x), 0.005, `${id} inverted vertex at ${v.x}`);
  });
  return series.vertices;
}
async function bestMatches(root, setting) {
  const { a, b, f, q } = setting, state = await chartState(root);
  chartContract(state, ['coverage', 'majority', 'verifier'], 0, 10, q);
  assert.equal(new Set(state.series.map(s => s.dash)).size, 3, 'distinct dash styles, not color alone');
  for (const name of ['coverage', 'majority', 'verifier']) {
    gridSeries(state, name, u => bestOracle(a, b, 2 ** Math.round(u), f)[name]);
    await percent(root, name, bestOracle(a, b, 2 ** q, f)[name]);
  }
  for (let i = 0; i < 11; i++) assert.ok(state.series.find(s => s.id === 'verifier').vertices[i].y <=
    state.series.find(s => s.id === 'coverage').vertices[i].y + 0.005, 'selection cannot exceed coverage');
  return state;
}

async function reviewEvidence() {
  const [bytes, review] = await Promise.all([readFile(file), readFile(reviewFile, 'utf8')]);
  const digest = createHash('sha256').update(bytes).digest('hex');
  assert.ok(review.toLowerCase().includes(digest), 'review binds to current page SHA-256');
  const length = String(bytes.length), commaLength = bytes.length.toLocaleString('en-US');
  assert.ok([length, commaLength].some(n => new RegExp(`(?:^|[^\\d])${n}(?:\\s|[*\x60])*bytes?\\b|\\b(?:bytes?|byte count|size)(?:[^\\d\\n]{0,30})${n}(?:[^\\d]|$)`, 'i').test(review)),
    'review records current byte count');
  return review;
}
function disclosedNumbers(text, values, label) {
  const numbers = (text.replace(/[−–—]/g, '-').match(/[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[-+]?\d+)?/gi) ?? []).map(Number);
  for (const value of values) assert.ok(numbers.some(n => Math.abs(n - value) < 1e-10), `${label}: visible constant ${value}`);
}

test('D1: self-contained cursus lab, three ordered panels and registered locked suite', async t => {
  const page = await pageFor(t);
  assert.equal(await page.locator('html').getAttribute('data-design-system'), 'cursus');
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'lab');
  assert.deepEqual(await page.locator('section[data-panel]').evaluateAll(nodes => nodes.map(n => n.id)), panelIds);
  assert.equal(await page.locator('script[src], script[type="module"]').count(), 0);
  const reserved = await page.locator('*').evaluateAll(nodes => nodes.flatMap(n => Array.from(n.attributes)
    .filter(a => a.name === 'data-lab' || a.name === 'data-reset' || a.name.startsWith('data-budget')).map(a => a.name)));
  assert.deepEqual(reserved, [], 'no starter budget markers');
  const pkg = JSON.parse(await readFile(path.join(repoRoot, 'setup/package.json'), 'utf8'));
  assert.match(pkg.scripts.test, /^node\s+--test\s/);
  const registered = pkg.scripts.test.trim().split(/\s+/).slice(2).map(p => path.resolve(repoRoot, 'setup', p));
  assert.equal(registered.filter(p => p === path.join(repoRoot, 'tools/html-pages/tests/test-time-compute.test.mjs')).length, 1);
  assert.equal(suites.filter(name => name === 'test-time-compute').length, 1, 'component tooling registration');
  for (const id of panelIds) {
    const root = panel(page, id);
    for (const selector of ['figure[data-ttc-chart]', 'output[data-ttc-readout]', 'button[data-ttc-reset]'])
      assert.equal(await root.locator(selector).count(), 1, `${id}: ${selector}`);
    assert.equal(await root.locator('button[data-ttc-reset]').isEnabled(), true);
  }
  const review = await reviewEvidence();
  for (const mode of [/desktop|1440/i, /laptop|1280/i, /390/, /no[ -]?(?:js|javascript)/i, /print/i, /reduced[ -]motion/i])
    assert.match(review, mode, 'named screenshot review evidence');
});

test('D2: keyboard-driven Beta search, verifier endpoints, chart geometry and reset', { timeout: 180000 }, async t => {
  const page = await pageFor(t), root = panel(page, 'best-of-n'), controls = await bestControls(root);
  const defaults = { a: 0.6, b: 2.4, f: 0.1, q: 4 };
  for (const setting of [defaults,
    { a: 0.3, b: 4.1, f: 0.35, q: 2 },
    { a: 4.6, b: 0.7, f: 0.85, q: 9 },
    { a: 0.2, b: 5, f: 0, q: 0 },
    { a: 5, b: 0.2, f: 1, q: 10 },
  ]) {
    await setBest(controls, setting);
    await eventually(() => bestMatches(root, setting));
    const expected = bestOracle(setting.a, setting.b, 2 ** setting.q, setting.f);
    for (const [method, name] of [['majorityAtN', 'majority'], ['verifierAtN', 'verifier']]) {
      const args = [setting.a, setting.b, 2 ** setting.q];
      if (method === 'verifierAtN') args.push(setting.f);
      near(await api(page, method, args), expected[name], 1e-8, method);
    }
  }
  // Odd sample counts and non-grid N prevent an implementation of just 11 examples.
  for (const [a, b, n, f] of [[1.7, 2.9, 2, 0.45], [0.6, 2.4, 3, 0.1], [0.3, 4.1, 7, 0.35], [4.6, 0.7, 23, 0.85], [1.7, 2.9, 129, 0.45]]) {
    const expected = bestOracle(a, b, n, f);
    near(await api(page, 'majorityAtN', [a, b, n]), expected.majority, 1e-8, 'off-grid majority');
    near(await api(page, 'verifierAtN', [a, b, n, f]), expected.verifier, 1e-8, 'off-grid verifier');
    near(await api(page, 'verifierAtN', [a, b, n, 0]), passOracle(a, b, n), 1e-9, 'perfect verifier = coverage');
    near(await api(page, 'verifierAtN', [a, b, n, 1]), a / (a + b), 1e-9, 'accept-all verifier = single-sample accuracy');
  }
  await setBest(controls, defaults);
  const before = await eventually(() => bestMatches(root, defaults));
  await setRange(controls.f, 1);
  const after = await eventually(() => bestMatches(root, { ...defaults, f: 1 }));
  for (const id of ['coverage', 'majority']) assert.deepEqual(before.series.find(s => s.id === id).vertices,
    after.series.find(s => s.id === id).vertices, `${id} is independent of verifier FPR`);
  await setRange(controls.f, 0);
  await eventually(() => bestMatches(root, { ...defaults, f: 0 }));
  await root.locator('button[data-ttc-reset]').click();
  for (const [key, value] of Object.entries(defaults)) near(Number(await controls[key].inputValue()), value);
  await eventually(() => bestMatches(root, defaults));
});

test('D3: disclosed difficulty sigmoid, inverse hinge, token/cost axes and reset', async t => {
  const page = await pageFor(t), root = panel(page, 'effort-dial');
  const params = (await paramsFor(page)).effort;
  assert.equal(params.xMin, 7); assert.equal(params.xMax, 15);
  assert.equal(params.pricePerMTok, 10, 'illustrative price');
  assert.ok(params.floor >= 0 && params.floor < 1 && params.slope > 0);
  assert.deepEqual(params.difficulties.map(d => d.id).sort(), ['easy', 'hard', 'medium']);
  for (const d of params.difficulties) assert.ok(Number.isFinite(d.mid) && d.ceil > params.floor && d.ceil <= 1);
  for (const name of ['ceil', 'mid', 'peak', 'lambda']) assert.ok(Number.isFinite(params.inverse[name]), `inverse.${name}`);
  assert.ok(params.inverse.ceil > params.floor && params.inverse.ceil <= 1 && params.inverse.lambda > 0);
  const formula = root.locator('[data-ttc-formula]');
  const text = await formula.innerText();
  assert.match(text, /sigmoid|σ/i); assert.match(text, /max/i);
  disclosedNumbers(text, [params.floor, params.slope, params.pricePerMTok, params.xMin, params.xMax,
    ...params.difficulties.flatMap(d => [d.ceil, d.mid]),
    ...['ceil', 'mid', 'peak', 'lambda'].map(k => params.inverse[k])], 'effort assumptions');
  assert.match(await root.innerText(), /illustrative price/i);
  assert.match(await root.innerText(), /not a vendor quote/i);
  const dial = root.locator('input[type=range]'), toggle = root.locator('input[type=checkbox]');
  await rangeContract(dial, 7, 15, 1, 10);
  assert.equal(await toggle.count(), 1); assert.equal(await toggle.isChecked(), false);
  assert.equal(await toggle.isEnabled(), true);
  for (let x = 7; x <= 15; x += 0.25) {
    const values = ['easy', 'medium', 'hard'].map(id => effortOracle(params, x, id));
    assert.ok(values[0] >= values[1] && values[1] >= values[2], 'easy >= medium >= hard over full domain');
    for (const id of ['easy', 'medium', 'hard']) near(await api(page, 'effortAccuracy', [x, id]), effortOracle(params, x, id), 1e-9);
    near(await api(page, 'inverseAccuracy', [x]), inverseOracle(params, x), 1e-9);
  }
  async function match(x, inverse = false) {
    const state = await chartState(root);
    chartContract(state, inverse ? ['easy', 'medium', 'hard', 'inverse'] : ['easy', 'medium', 'hard'], 7, 15, x);
    for (const id of ['easy', 'medium', 'hard']) {
      const vertices = gridSeries(state, id, u => effortOracle(params, u, id), { min: 7, max: 15, integer: false });
      for (let i = 1; i < vertices.length; i++) assert.ok(vertices[i].y >= vertices[i - 1].y - 1e-6, `${id} non-decreasing`);
      await percent(root, id, effortOracle(params, x, id));
    }
    const inverseMetric = root.locator('span[data-metric="inverse"]');
    if (inverse) {
      const vertices = gridSeries(state, 'inverse', u => inverseOracle(params, u), { min: 7, max: 15, integer: false });
      const peak = Math.max(...vertices.map(v => v.y)), peakIndex = vertices.findIndex(v => v.y === peak);
      assert.ok(peakIndex > 0 && peakIndex < vertices.length - 1, 'inverse peak is interior');
      assert.ok(peak - vertices.at(-1).y >= 0.1, 'inverse accuracy drops at least 10 percentage points');
      assert.notEqual(state.series.find(s => s.id === 'inverse').dash, 'none', 'inverse curve dashed');
      await percent(root, 'inverse', inverseOracle(params, x));
    } else assert.ok(await inverseMetric.count() === 0 || !(await inverseMetric.isVisible()), 'inverse metric hidden until enabled');
    await integerMetric(root, 'tokens', 2 ** x);
    await costMetric(root, 2 ** x * params.pricePerMTok / 1e6);
    return state;
  }
  for (const x of [7, 10, 15]) { await setRange(dial, x); await eventually(() => match(x)); }
  const axis = root.locator('g[data-axis="cost"]');
  assert.equal(await axis.count(), 1);
  const ticks = await axis.locator('text[data-tokens]').evaluateAll(nodes => nodes.map(n => {
    const svg = n.ownerSVGElement;
    const localToSvg = svg.getScreenCTM().inverse().multiply(n.getScreenCTM());
    const anchor = new DOMPoint(n.x.baseVal.numberOfItems ? n.x.baseVal.getItem(0).value : 0,
      n.y.baseVal.numberOfItems ? n.y.baseVal.getItem(0).value : 0).matrixTransform(localToSvg);
    return { tokens: Number(n.dataset.tokens), text: n.textContent.trim(), x: anchor.x };
  }));
  assert.ok(ticks.length >= 2 && new Set(ticks.map(t => t.tokens)).size === ticks.length, 'distinct cost ticks');
  const state = await chartState(root);
  for (const tick of ticks) {
    assert.ok(tick.tokens >= 128 && tick.tokens <= 32768);
    const expected = tick.tokens * params.pricePerMTok / 1e6;
    near(money(tick.text, false), expected, Math.max(1e-7, expected * 0.02), 'cost axis amount');
    near(tick.x, state.area.x + (Math.log2(tick.tokens) - 7) / 8 * state.area.width, 0.5, 'cost tick log2 position');
  }
  await toggle.check();
  for (const x of [7, 11, 15]) { await setRange(dial, x); await eventually(() => match(x, true)); }
  await setRange(dial, 10);
  const lowCost = await eventually(() => costMetric(root, 1024 * params.pricePerMTok / 1e6));
  await setRange(dial, 11);
  const highCost = await eventually(() => costMetric(root, 2048 * params.pricePerMTok / 1e6));
  near(highCost / lowCost, 2, 0.05, 'doubling tokens doubles cost');
  await root.locator('button[data-ttc-reset]').click();
  assert.equal(Number(await dial.inputValue()), 10); assert.equal(await toggle.isChecked(), false);
  await eventually(() => match(10));
});

test('D4: disclosed Beta mixtures cross once, agree with every k, and follow the slider', async t => {
  const page = await pageFor(t), root = panel(page, 'sharpen-or-expand'), mixtures = (await paramsFor(page)).mixtures;
  const formula = await root.locator('[data-ttc-formula]').innerText();
  assert.match(formula, /Beta|β|B\s*\(/i); assert.match(formula, /base/i); assert.match(formula, /RL|tuned/i);
  for (const name of ['base', 'rl']) {
    const components = mixtures[name];
    assert.ok(Array.isArray(components) && components.length >= 2, `${name}: Beta mixture`);
    for (const c of components) {
      assert.ok([c.w, c.a, c.b].every(v => Number.isFinite(v) && v > 0), 'positive finite mixture components');
      disclosedNumbers(formula, [c.w, c.a, c.b], `${name} mixture`);
    }
    near(sum(components.map(c => c.w)), 1, 1e-10, 'normalized mixture');
  }
  const expected = Array.from({ length: 1024 }, (_, i) => ({ k: i + 1,
    base: mixtureOracle(mixtures.base, i + 1), rl: mixtureOracle(mixtures.rl, i + 1) }));
  assert.ok(expected[0].rl > expected[0].base, 'RL leads at k=1');
  assert.ok(expected.at(-1).base > expected.at(-1).rl, 'base leads at k=1024');
  const signs = expected.map(v => Math.sign(v.base - v.rl)).filter(v => v !== 0);
  assert.equal(signs.slice(1).filter((v, i) => v !== signs[i]).length, 1, 'exactly one integer-grid sign change');
  const crossing = expected.find(v => v.base >= v.rl).k;
  assert.ok(crossing >= 4 && crossing <= 256, 'crossing in [4,256]');
  assert.equal(await api(page, 'crossingK'), crossing);
  const actual = await page.evaluate(mixtures => Array.from({ length: 1024 }, (_, i) => ({
    base: window.TestTimeCompute.passAtKMixture(mixtures.base, i + 1),
    rl: window.TestTimeCompute.passAtKMixture(mixtures.rl, i + 1),
  })), mixtures);
  actual.forEach((v, i) => { near(v.base, expected[i].base, 1e-9, `base@${i + 1}`); near(v.rl, expected[i].rl, 1e-9, `rl@${i + 1}`); });
  const dial = root.locator('input[type=range]');
  assert.equal(await dial.count(), 1);
  const defaultK = Number(await dial.inputValue());
  assert.ok(Number.isInteger(defaultK) && defaultK >= 0 && defaultK <= 10, 'default log2k');
  await rangeContract(dial, 0, 10, 1, defaultK);
  async function match(q) {
    const state = await chartState(root);
    chartContract(state, ['base', 'rl'], 0, 10, q);
    for (const name of ['base', 'rl']) {
      gridSeries(state, name, u => mixtureOracle(mixtures[name], 2 ** Math.round(u)));
      await percent(root, name, mixtureOracle(mixtures[name], 2 ** q));
    }
    await integerMetric(root, 'crossing', crossing);
    assert.equal(state.crossings.length, 1, 'one crossing marker');
    assert.equal(state.crossings[0].tag, 'line', 'vertical crossing line');
    assert.ok(state.crossings[0].height > 0, 'crossing line has visible length');
    assert.equal(state.crossings[0].xs.length, 2);
    state.crossings[0].xs.forEach(x => near(x, Math.log2(crossing), 0.005, 'crossing log2 position'));
  }
  for (let q = 0; q <= 10; q++) { await setRange(dial, q); await eventually(() => match(q)); }
  await root.locator('button[data-ttc-reset]').click();
  assert.equal(Number(await dial.inputValue()), defaultK); await eventually(() => match(defaultK));
});

test('D5: visible formulas, modelling assumptions, simulation labels and panel citations', async t => {
  const page = await pageFor(t);
  for (let i = 0; i < panelIds.length; i++) {
    const root = panel(page, panelIds[i]);
    const formula = root.locator('[data-ttc-formula]'), callout = root.locator('.callout[data-illustrative]');
    assert.equal(await formula.count(), 1); assert.equal(await formula.isVisible(), true);
    assert.equal(await callout.count(), 1); assert.equal(await callout.isVisible(), true);
    assert.match(await callout.innerText(), /illustrative simulation/i);
    const caption = root.locator('figure[data-ttc-chart] figcaption');
    assert.equal(await caption.count(), 1); assert.equal(await caption.isVisible(), true);
    assert.match(await caption.innerText(), /illustrative simulation/i);
    const links = await caption.locator('a[href]').evaluateAll(nodes => nodes.map(n => n.href));
    for (const id of sources[i]) assert.ok(links.some(href => {
      const url = new URL(href);
      return /^(?:www\.)?arxiv\.org$/i.test(url.hostname) && new RegExp(`/(?:abs|pdf)/${id.replace('.', '\\.')}(?:v\\d+)?(?:\\.pdf)?/?$`).test(url.pathname);
    }), `panel citation: arXiv ${id}`);
  }
  const best = await panel(page, 'best-of-n').locator('[data-ttc-formula]').innerText();
  const normalized = mathText(best);
  assert.match(normalized, /1-\(1-p\)\^?N/i, 'heterogeneous pass@N formula');
  assert.match(normalized, /B\(a,b\+N\)/i); assert.match(normalized, /B\(a,b\)/i);
  assert.match(best, /Beta|β/i); assert.match(best, /binary|two[ -](?:answer|class)/i);
  assert.match(best, /distractor|same wrong|shared wrong|single wrong/i);
  assert.match(best, /tie/i); assert.match(best, /half|½|0\.5|50\s*%/i);
  assert.match(best, /true[ -]positive/i); assert.match(best, /uniform|random order/i);
  assert.match(normalized, /K=0[^.]{0,100}(?:zero|0)/i, 'K=0 contributes zero');
  assert.match(best, /∞|infinity|infinite|limit/i);
  assert.match(normalized, /P\(p>(?:1\/2|0\.5)\)/i, 'majority limiting success');
  assert.match(normalized, /p\/\(p\+f(?:pr)?(?:[·×*])?\(1-p\)\)/i, 'verifier limiting success');
  const rlText = await panel(page, 'sharpen-or-expand').innerText();
  assert.match(rlText, /contested/i);
  assert.match(rlText, /no problem[^.\n]*unsolvable|(?:every|all) problem[^.\n]*(?:solvable|positive|nonzero|non-zero)/i);
  assert.match(rlText, /slow[^.\n]*converg|converg[^.\n]*slow/i);
  const review = await reviewEvidence();
  assert.match(review, /citation|source|prose/i, 'named citation/prose review');
  assert.match(review, /accurate|accuracy|checked|verified|consistent|supports/i, 'written citation assessment');
});

test('D5: each predict card locks, reveals correct/incorrect feedback, resets, and asks the agreed question', async t => {
  const page = await pageFor(t);
  for (const [i, id] of panelIds.entries()) {
    const root = panel(page, id).locator('[data-predict]');
    assert.equal(await root.count(), 1);
    assert.equal(await root.locator('fieldset[data-predict-question]').count(), 1);
    const correct = root.locator('input[type=radio][data-correct]');
    const wrong = root.locator('input[type=radio]:not([data-correct])').first();
    assert.equal(await correct.count(), 1); assert.ok(await root.locator('input[type=radio]').count() >= 2);
    const label = await correct.evaluate(n => n.getAttribute('aria-label') ?? Array.from(n.labels ?? [], l => l.textContent).join(' '));
    assert.match(label, [/coverage|pass\s*@\s*N/i, /falls?|decreas|lower|worse|declin/i, /base/i][i]);
    const question = await root.locator('legend').innerText();
    if (i === 0) {
      assert.match(question, /10\s*%/); assert.match(question, /100\s*%/); assert.match(question, /limit|∞|infin|without bound/i);
    } else if (i === 1) { assert.match(question, /doubl/i); assert.match(question, /tokens?/i); assert.match(question, /inverse|peak/i); }
    else assert.match(question, /1,?024/);
    for (const choice of [correct, wrong]) {
      await initialPredict(root);
      await choice.check();
      assert.equal(await root.locator('[data-predict-lock]').isEnabled(), true);
      assert.equal(await root.locator('[data-predict-reveal]').isEnabled(), false);
      await root.locator('[data-predict-lock]').click();
      for (const radio of await root.locator('input[type=radio]').all()) assert.equal(await radio.isEnabled(), false);
      assert.equal(await root.locator('[data-predict-answer]').isVisible(), false);
      assert.equal(await root.locator('[data-predict-reveal]').isEnabled(), true);
      await root.locator('[data-predict-reveal]').click();
      assert.equal(await root.locator('[data-predict-answer]').isVisible(), true);
      const result = await root.locator('[data-predict-result]').innerText();
      assert.match(result, choice === correct ? /^Correct\./i : /^Not quite\./i);
      const explanation = await root.locator('[data-predict-answer]').innerText();
      if (i === 0) { assert.match(explanation, /majority/i); assert.match(explanation, /verifier/i); assert.match(explanation, /limit|∞|infin/i); }
      if (i === 2) { assert.match(explanation, /contested/i); assert.match(explanation, /model|simulat/i); assert.match(explanation, /not.*measur|not.*empirical|illustrative/i); }
      await root.locator('[data-predict-reset]').click();
      await initialPredict(root);
    }
  }
});

test('D5: no-JS and print preserve formulas, assumptions, answers and citations', async t => {
  const staticPage = await pageFor(t, { javaScriptEnabled: false });
  assert.match(await staticPage.locator('body').innerText(), /charts?[^.\n]*(?:browser|JavaScript)|(?:browser|JavaScript)[^.\n]*charts?/i);
  for (const id of panelIds) {
    const root = panel(staticPage, id);
    for (const selector of ['[data-ttc-formula]', '[data-predict-answer]', '.callout[data-illustrative]', 'figcaption'])
      assert.equal(await root.locator(selector).isVisible(), true, `no-JS ${id}: ${selector}`);
    for (const button of await root.locator('[data-predict] button').all()) assert.equal(await button.isEnabled(), false);
  }
  const printPage = await pageFor(t);
  await printPage.emulateMedia({ media: 'print' });
  for (const id of panelIds) {
    const root = panel(printPage, id);
    for (const selector of ['[data-ttc-formula]', '[data-predict-answer]', 'figure[data-ttc-chart] > svg', 'figcaption'])
      assert.equal(await root.locator(selector).isVisible(), true, `print ${id}: ${selector}`);
  }
});

test('A1: independent oracle self-checks, including singular Beta shapes and recommended crossing', () => {
  for (const n of [0, 1, 2, 5, 16, 64, 256]) {
    near(passOracle(1, 1, n), n / (n + 1));
    near(passOracle(1, 2, n), n / (n + 2));
    near(passOracle(2, 1, n), 1 - 2 / ((n + 1) * (n + 2)));
    near(passOracle(2, 3, n), 1 - 12 / ((n + 3) * (n + 4)));
  }
  near(bestOracle(1, 1, 2, 0).coverage, 2 / 3);
  near(bestOracle(1, 1, 2, 1).verifier, 1 / 2);
  near(bestOracle(1, 1, 2, 0.5).verifier, 7 / 12);
  near(bestOracle(1, 1, 2, 0.5).majority, 1 / 2);
  for (const [a, b] of [[0.6, 2.4], [0.3, 4.1], [4.6, 0.7], [0.2, 5], [5, 0.2]]) {
    const perfect = bestOracle(a, b, 1024, 0), acceptAll = bestOracle(a, b, 1024, 1);
    near(perfect.verifier, passOracle(a, b, 1024), 2e-9, 'oracle verifier/coverage identity at 1024');
    near(acceptAll.verifier, a / (a + b), 2e-9, 'oracle accept-all identity at 1024');
    for (const name of ['coverage', 'majority', 'verifier']) probability(perfect[name], `oracle ${name}`);
  }
  for (const [a, b] of [[0.6, 2.4], [0.2, 5]]) {
    const ns = [1, 5, 64], estimates = monteCarlo(a, b, ns, 310021);
    estimates.forEach((value, i) => near(value, passOracle(a, b, ns[i]), 0.01, 'seeded Beta oracle sanity'));
  }
  const base = [{ w: 0.6, a: 1, b: 3 }, { w: 0.4, a: 0.5, b: 8 }];
  const rl = [{ w: 0.6, a: 4, b: 1 }, { w: 0.4, a: 0.08, b: 8 }];
  const crossing = Array.from({ length: 1024 }, (_, i) => i + 1).find(k => mixtureOracle(base, k) >= mixtureOracle(rl, k));
  assert.ok(crossing >= 4 && crossing <= 256, 'recommended mixtures are feasible');
});

test('A1: page pass@N unit tests use exact identities, quadrature and seeded Monte Carlo', { timeout: 120000 }, async t => {
  const page = await pageFor(t);
  const members = await page.evaluate(() => Object.fromEntries(
    ['passAtN', 'majorityAtN', 'verifierAtN', 'passAtKMixture', 'effortAccuracy', 'inverseAccuracy', 'crossingK'].map(k => [k, typeof window.TestTimeCompute?.[k]])));
  for (const [name, type] of Object.entries(members)) assert.equal(type, 'function', `public API ${name}`);
  for (const n of [0, 1, 2, 5, 16, 64, 256]) {
    for (const [a, b, expected] of [[1, 1, n / (n + 1)], [1, 2, n / (n + 2)],
      [2, 1, 1 - 2 / ((n + 1) * (n + 2))], [2, 3, 1 - 12 / ((n + 3) * (n + 4))]])
      near(await api(page, 'passAtN', [a, b, n]), expected, 1e-10, `Beta(${a},${b})@${n}`);
  }
  for (const [a, b, n] of [[1.4, 2.7, 3], [2.3, 4.2, 17], [4.7, 1.6, 61]])
    near(await api(page, 'passAtN', [a, b, n]), midpointOracle(a, b, n), 1e-6, 'independent integral ratio');
  for (const [a, b] of [[0.6, 2.4], [0.2, 5]]) {
    const ns = [1, 5, 64, 256], estimates = monteCarlo(a, b, ns, 310031);
    for (let i = 0; i < ns.length; i++) near(await api(page, 'passAtN', [a, b, ns[i]]), estimates[i], 0.01, 'independent 200k-draw MC');
  }
  for (const [a, b] of [[0.2, 5], [0.7, 3.9], [4.8, 0.3], [1.7, 2.6]]) {
    near(await api(page, 'passAtN', [a, b, 0]), 0, 1e-12);
    near(await api(page, 'passAtN', [a, b, 1]), a / (a + b), 1e-12);
    let previous = 0;
    for (const n of [1, 2, 7, 19, 137, 1024]) {
      const current = await api(page, 'passAtN', [a, b, n]);
      probability(current, 'pass@N'); assert.ok(current >= previous, 'monotone coverage'); previous = current;
    }
  }
  near(await api(page, 'passAtN', [1, 1, 2]), 2 / 3, 1e-12, 'heterogeneity, not 1-(1-E[p])^2');
  near(await api(page, 'passAtN', [1, 1, 1000000]), 1000000 / 1000001, 1e-11, 'large N exact identity');
  const mixture = [{ w: 0.17, a: 0.3, b: 4.1 }, { w: 0.29, a: 2.6, b: 1.3 }, { w: 0.54, a: 4.7, b: 3.2 }];
  for (const k of [0, 1, 3, 17, 113, 1024]) near(await api(page, 'passAtKMixture', [mixture, k]), mixtureOracle(mixture, k), 1e-10, 'alternate mixture linearity');
  const invalid = await page.evaluate(() => {
    const badShape = [0, -1, NaN, Infinity, -Infinity, undefined, null, '1'];
    const badN = [-1, 0.5, NaN, Infinity, -Infinity, undefined, null, '2'];
    const cases = [...badShape.flatMap(v => [[v, 2, 3], [2, v, 3], [v, 2, 0], [2, v, 0]]), ...badN.map(v => [1, 2, v])];
    return cases.map(args => { try { window.TestTimeCompute.passAtN(...args); return false; } catch { return true; } });
  });
  assert.ok(invalid.every(Boolean), 'invalid a, b, N throw, even at N=0');
});

test('A1: repeated offline loads and resets give identical numerical state', async t => {
  const page = await pageFor(t);
  await eventually(async () => {
    for (const id of panelIds) assert.ok((await chartState(panel(page, id))).series.length >= 2, 'initial charts rendered');
  });
  const snapshot = () => page.locator('section[data-panel]').evaluateAll(nodes => nodes.map(n => ({
    readout: n.querySelector('output[data-ttc-readout]').textContent,
    curves: Array.from(n.querySelectorAll('polyline[data-series]'), s => [s.dataset.series, s.getAttribute('points')]),
  })));
  const first = await snapshot();
  await page.reload();
  await eventually(async () => assert.deepEqual(await snapshot(), first, 'two loads are deterministic'));
  for (const id of panelIds) await panel(page, id).locator('button[data-ttc-reset]').click();
  await eventually(async () => assert.deepEqual(await snapshot(), first, 'panel resets reproduce initial state'));
});

async function mobileReadable(page) {
  const documentSize = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth }));
  assert.ok(documentSize.scroll <= documentSize.width, 'no horizontal document overflow');
  for (const id of panelIds) {
    const root = panel(page, id), figure = root.locator('figure[data-ttc-chart]');
    assert.equal(await figure.isVisible(), true);
    const geometry = await figure.evaluate(figure => {
      const svg = figure.querySelector(':scope > svg'), box = svg.getBoundingClientRect(), css = getComputedStyle(figure);
      const texts = Array.from(svg.querySelectorAll('text')).filter(n => {
        const s = getComputedStyle(n);
        return n.getClientRects().length && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
      }).map(n => {
        const r = n.getBoundingClientRect();
        return { text: n.textContent.trim(), x: r.x, y: r.y, right: r.right, bottom: r.bottom,
          width: r.width, height: r.height, font: parseFloat(getComputedStyle(n).fontSize) };
      }).filter(n => n.text);
      return { x: box.x, y: box.y, right: box.right, bottom: box.bottom, width: box.width, height: box.height,
        viewWidth: svg.viewBox.baseVal.width, figureWidth: figure.clientWidth, texts,
        marginLeft: parseFloat(css.marginLeft), marginRight: parseFloat(css.marginRight) };
    });
    assert.ok(geometry.width >= 300, `${id}: chart at least 300 px wide`);
    assert.ok(geometry.x >= -0.5 && geometry.right <= documentSize.width + 0.5, `${id}: SVG inside viewport`);
    near(geometry.viewWidth, geometry.figureWidth, 1, `${id}: viewBox responds to actual container width`);
    near(geometry.marginLeft, 0, 0.01, 'figure margin'); near(geometry.marginRight, 0, 0.01, 'figure margin');
    assert.ok(geometry.texts.length >= 4, `${id}: visible axis text`);
    for (const text of geometry.texts) {
      assert.ok(text.height >= 12 && text.font >= 12, `${id}: readable text ${text.text}`);
      assert.ok(text.x >= geometry.x - 0.5 && text.right <= geometry.right + 0.5 &&
        text.y >= geometry.y - 0.5 && text.bottom <= geometry.bottom + 0.5, `${id}: unclipped text ${text.text}`);
    }
    for (let i = 0; i < geometry.texts.length; i++) for (let j = i + 1; j < geometry.texts.length; j++) {
      const a = geometry.texts[i], b = geometry.texts[j];
      const overlapX = Math.min(a.right, b.right) - Math.max(a.x, b.x);
      const overlapY = Math.min(a.bottom, b.bottom) - Math.max(a.y, b.y);
      assert.ok(overlapX <= 0.5 || overlapY <= 0.5, `${id}: text collision between '${a.text}' and '${b.text}'`);
    }
    const axisText = geometry.texts.map(t => t.text).join(' ');
    assert.match(axisText, /accuracy|success|probability|coverage|pass/i, `${id}: accuracy axis label`);
    assert.match(axisText, id === 'effort-dial' ? /tokens?/i : id === 'best-of-n' ? /\bN\b|samples?/i : /\bk\b/i, `${id}: compute axis label`);
    const legendText = await root.locator('ul, ol, [role=list]').evaluateAll(nodes => nodes.filter(n => n.getClientRects().length).map(n => n.innerText));
    const labelText = `${axisText} ${legendText.join(' ')}`;
    const labels = id === 'best-of-n' ? [/coverage|pass\s*@\s*N/i, /majority/i, /verifier/i] :
      id === 'effort-dial' ? [/easy/i, /medium/i, /hard/i] : [/base/i, /RL|tuned/i];
    if (id === 'effort-dial' && await root.locator('input[type=checkbox]').isChecked()) labels.push(/inverse/i);
    labels.forEach(label => assert.match(labelText, label, `${id}: direct series label or legend`));
    assert.equal(await root.locator('output[data-ttc-readout]').isVisible(), true, `${id}: readout visible`);
  }
}

test('A2: 390px stress states keep labels, axes and readouts readable; resize rebuilds charts', { timeout: 180000 }, async t => {
  const page = await pageFor(t, { viewport: { width: 390, height: 844 } });
  const best = panel(page, 'best-of-n'), controls = await bestControls(best);
  await eventually(() => mobileReadable(page));
  const effort = panel(page, 'effort-dial'), k = panel(page, 'sharpen-or-expand').locator('input[type=range]');
  await setBest(controls, { a: 0.6, b: 2.4, f: 1, q: 10 });
  await effort.locator('input[type=checkbox]').check();
  for (const [q, x] of [[0, 11], [10, 15]]) {
    await setRange(k, q); await setRange(effort.locator('input[type=range]'), x);
    await eventually(() => mobileReadable(page));
  }
  await setBest(controls, { a: 5, b: 0.2, f: 1, q: 10 });
  await eventually(() => mobileReadable(page));
  await page.setViewportSize({ width: 1280, height: 900 });
  await eventually(async () => {
    for (const id of panelIds) {
      const root = panel(page, id), state = await chartState(root);
      const width = await root.locator('figure[data-ttc-chart]').evaluate(el => el.clientWidth);
      near(state.viewBox.width, width, 1, 'desktop resize redraw');
    }
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await eventually(() => mobileReadable(page));
  await eventually(() => bestMatches(best, { a: 5, b: 0.2, f: 1, q: 10 }));
  const review = await reviewEvidence();
  assert.match(review, /390/); assert.match(review, /screenshot|visual|inspect/i);
});

test('A2: reduced motion retains functioning controls and disables transitions/animations', async t => {
  const page = await pageFor(t, { reducedMotion: 'reduce' });
  const motion = await page.locator('section[data-panel], section[data-panel] *').evaluateAll(nodes => nodes.flatMap(n => {
    const style = getComputedStyle(n);
    const durations = [...style.animationDuration.split(','), ...style.transitionDuration.split(',')];
    return durations.filter(s => parseFloat(s) > 0.001).map(s => `${n.tagName}: ${s}`);
  }));
  assert.deepEqual(motion, [], 'reduced motion disables nonessential transitions');
  const root = panel(page, 'best-of-n'), controls = await bestControls(root);
  await setRange(controls.q, 5);
  await eventually(() => bestMatches(root, { a: 0.6, b: 2.4, f: 0.1, q: 5 }));
});
