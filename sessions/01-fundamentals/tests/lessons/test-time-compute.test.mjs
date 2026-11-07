import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../../../../tools/html-pages/browser.mjs';
import { repoRoot, eventually } from '../../../../tools/html-pages/tests/component-helpers.mjs';

/* The test-time-compute lab's three models, with expected numbers computed here, never with the
 * page's API as the oracle. PARAMS.effort.inverse.ceil is the sigmoid's upper asymptote:
 * floor + (ceil-floor)*sigmoid - lambda*hinge. The beta-binomial majority rule, with half credit for
 * ties, is the contract; only coverage need be monotone in N. Prose, citations, layout,
 * accessibility and the no-JS view are reviewed by a person or by the page checker, not here.
 */
const file = path.join(repoRoot, 'sessions/01-fundamentals/cursus/labs/test-time-compute.html');
const panel = id => page.locator(`section[data-panel]#${id}`);
const sum = xs => xs.reduce((a, b) => a + b, 0);
const sigmoid = x => 1 / (1 + Math.exp(-x));

function near(actual, expected, tolerance = 1e-9, label = 'value') {
  assert.ok(Number.isFinite(actual) && Number.isFinite(expected), `${label}: finite (${actual}, ${expected})`);
  assert.ok(Math.abs(actual - expected) <= tolerance,
    `${label}: ${actual} != ${expected}, tolerance ${tolerance}`);
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
let browser, page;
const errors = [];
before(async () => {
  browser = await chromium.launch();
  const context = await browser.newContext({ offline: true, viewport: { width: 1280, height: 900 } });
  await context.route(/^(?:https?|wss?|ftp):/i, route => { errors.push(`remote request: ${route.request().url()}`); return route.abort(); });
  page = await context.newPage();
  page.setDefaultTimeout(5000);
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(pathToFileURL(file).href);
});
after(() => browser?.close());
const paramsFor = () => page.evaluate(() => window.TestTimeCompute.PARAMS);

async function bestControls(root) {
  const ranges = root.locator('input[type=range]');
  const data = await ranges.evaluateAll(nodes => nodes.map(n => ({ min: Number(n.min), max: Number(n.max), value: Number(n.value) })));
  const find = predicate => {
    const indices = data.flatMap((d, i) => predicate(d) ? [i] : []);
    assert.equal(indices.length, 1, 'uniquely identifiable range');
    return ranges.nth(indices[0]);
  };
  return {
    a: find(d => d.min === 0.2 && d.max === 5 && d.value === 0.6),
    b: find(d => d.min === 0.2 && d.max === 5 && d.value === 2.4),
    f: find(d => d.min === 0 && d.max === 1),
    q: find(d => d.min === 0 && d.max === 10),
  };
}
async function setRange(input, value) {
  const [min, max, step] = await input.evaluate(el => [Number(el.min), Number(el.max), Number(el.step)]);
  assert.ok(value >= min && value <= max);
  if (Math.abs(Number(await input.inputValue()) - value) < 1e-10) return;
  await input.focus();
  // Real keyboard input, from the nearer end.
  const fromLow = Math.round((value - min) / step), fromHigh = Math.round((max - value) / step);
  await input.press(fromLow <= fromHigh ? 'Home' : 'End');
  for (let i = 0; i < Math.min(fromLow, fromHigh); i++) await input.press(fromLow <= fromHigh ? 'ArrowRight' : 'ArrowLeft');
  near(Number(await input.inputValue()), value, 1e-10, 'keyboard selection');
}
async function setBest(controls, { a, b, f, q }) {
  for (const [key, value] of Object.entries({ a, b, f, q })) await setRange(controls[key], value);
}
const metricText = (root, name) => root.locator(`output[data-ttc-readout] span[data-metric="${name}"]:visible`).innerText();
async function percent(root, name, expected) {
  const text = await metricText(root, name);
  const value = Number(text.match(/(\d+(?:\.\d+)?)\s*%/)?.[1]);
  near(value / 100, expected, 0.00051, `${name} readout (${text})`);
}
async function integerMetric(root, name, expected) {
  assert.equal(Number((await metricText(root, name)).replace(/[,\s]/g, '')), expected, name);
}
function money(text, requireSymbol = true) {
  const normalized = text.replace(/,/g, '').trim();
  const match = normalized.match(/\$\s*(\d+(?:\.\d+)?(?:e[-+]?\d+)?)|(\d+(?:\.\d+)?(?:e[-+]?\d+)?)\s*\$/i);
  // Axis units may live in the axis title; the cost readout includes dollars.
  if (!requireSymbol && !match && /^\d+(?:\.\d+)?(?:e[-+]?\d+)?$/i.test(normalized)) return Number(normalized);
  assert.ok(match, `dollar value: ${text}`);
  return Number(match[1] ?? match[2]);
}
async function costMetric(root, expected) {
  const value = money(await metricText(root, 'cost'));
  near(value, expected, Math.max(1e-7, expected * 0.02), 'cost readout');
  return value;
}

// Each curve's vertices, read back into data coordinates through the declared plot area and bounds.
async function chartState(root) {
  return root.locator('figure[data-ttc-chart] > svg').evaluate(svg => {
    const rects = svg.querySelectorAll('rect[data-plot-area]');
    if (rects.length !== 1) throw new Error('one declared plot area');
    const r = rects[0], area = { x: r.x.baseVal.value, y: r.y.baseVal.value, width: r.width.baseVal.value, height: r.height.baseVal.value };
    const bounds = { xMin: Number(svg.dataset.xMin), xMax: Number(svg.dataset.xMax), yMin: Number(svg.dataset.yMin), yMax: Number(svg.dataset.yMax) };
    const invertX = x => bounds.xMin + (x - area.x) / area.width * (bounds.xMax - bounds.xMin);
    const xOf = node => {
      if (node.tagName.toLowerCase() === 'circle') return [node.cx.baseVal.value];
      if (node.tagName.toLowerCase() === 'line') return [node.x1.baseVal.value, node.x2.baseVal.value];
      throw new Error('selection/crossing markers must be circles or lines');
    };
    return { area, bounds,
      series: Array.from(svg.querySelectorAll('polyline[data-series]'), line => ({
        id: line.dataset.series,
        vertices: Array.from(line.points, point => ({
          x: invertX(point.x), y: bounds.yMin + (1 - (point.y - area.y) / area.height) * (bounds.yMax - bounds.yMin),
        })),
      })),
      markers: Array.from(svg.querySelectorAll('[data-marker]'), node => xOf(node).map(invertX)),
      crossings: Array.from(svg.querySelectorAll('[data-crossing]'), node => xOf(node).map(invertX)),
    };
  });
}
function chartContract(state, ids, xMin, xMax, selected) {
  assert.deepEqual(state.series.map(s => s.id).sort(), [...ids].sort(), 'exact series set');
  for (const [key, value] of Object.entries({ xMin, xMax, yMin: 0, yMax: 1 })) near(state.bounds[key], value, 1e-12, key);
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
    near(v.y, oracle(v.x), 0.005, `${id} inverted vertex at ${v.x}`);
  });
  return series.vertices;
}
async function bestMatches(root, setting) {
  const { a, b, f, q } = setting, state = await chartState(root);
  chartContract(state, ['coverage', 'majority', 'verifier'], 0, 10, q);
  for (const name of ['coverage', 'majority', 'verifier']) {
    gridSeries(state, name, u => bestOracle(a, b, 2 ** Math.round(u), f)[name]);
    await percent(root, name, bestOracle(a, b, 2 ** q, f)[name]);
  }
  return state;
}

test('pass@N, majority and verifier match exact identities, quadrature and the beta-binomial oracle', async () => {
  const identities = [];
  for (const n of [0, 1, 2, 5, 16, 64, 256]) {
    for (const [a, b, expected] of [[1, 1, n / (n + 1)], [1, 2, n / (n + 2)],
      [2, 1, 1 - 2 / ((n + 1) * (n + 2))], [2, 3, 1 - 12 / ((n + 3) * (n + 4))]]) identities.push({ args: [a, b, n], expected, tolerance: 1e-10 });
  }
  for (const [a, b, n] of [[1.4, 2.7, 3], [2.3, 4.2, 17], [4.7, 1.6, 61]]) identities.push({ args: [a, b, n], expected: midpointOracle(a, b, n), tolerance: 1e-6 });
  identities.push({ args: [1, 1, 2], expected: 2 / 3, tolerance: 1e-12 }); // heterogeneity, not 1-(1-E[p])^2
  identities.push({ args: [1, 1, 1000000], expected: 1000000 / 1000001, tolerance: 1e-11 });
  const off = [[1.7, 2.9, 2, 0.45], [0.6, 2.4, 3, 0.1], [0.3, 4.1, 7, 0.35], [4.6, 0.7, 23, 0.85], [1.7, 2.9, 129, 0.45]];
  const mixture = [{ w: 0.17, a: 0.3, b: 4.1 }, { w: 0.29, a: 2.6, b: 1.3 }, { w: 0.54, a: 4.7, b: 3.2 }];
  const ks = [0, 1, 3, 17, 113, 1024];
  const got = await page.evaluate(({ identities, off, mixture, ks }) => {
    const T = window.TestTimeCompute;
    return {
      pass: identities.map(({ args }) => T.passAtN(...args)),
      off: off.map(([a, b, n, f]) => ({ majority: T.majorityAtN(a, b, n), verifier: T.verifierAtN(a, b, n, f),
        perfect: T.verifierAtN(a, b, n, 0), acceptAll: T.verifierAtN(a, b, n, 1) })),
      mixture: ks.map(k => T.passAtKMixture(mixture, k)),
    };
  }, { identities, off, mixture, ks });
  identities.forEach(({ args, expected, tolerance }, i) => near(got.pass[i], expected, tolerance, `passAtN(${args})`));
  off.forEach(([a, b, n, f], i) => {
    const expected = bestOracle(a, b, n, f);
    near(got.off[i].majority, expected.majority, 1e-8, 'off-grid majority');
    near(got.off[i].verifier, expected.verifier, 1e-8, 'off-grid verifier');
    near(got.off[i].perfect, passOracle(a, b, n), 1e-9, 'perfect verifier = coverage');
    near(got.off[i].acceptAll, a / (a + b), 1e-9, 'accept-all verifier = single-sample accuracy');
  });
  ks.forEach((k, i) => near(got.mixture[i], mixtureOracle(mixture, k), 1e-10, `mixture pass@${k}`));
  assert.deepEqual(errors, []);
});

test('best of N: the sliders drive the three curves and readouts; the FPR leaves coverage and majority alone; reset restores', async () => {
  const root = panel('best-of-n'), controls = await bestControls(root);
  const defaults = { a: 0.6, b: 2.4, f: 0.1, q: 4 };
  for (const setting of [defaults, { a: 0.3, b: 4.1, f: 0.35, q: 2 }, { a: 5, b: 0.2, f: 1, q: 10 }]) {
    await setBest(controls, setting);
    await eventually(() => bestMatches(root, setting));
  }
  await setBest(controls, defaults);
  const before = await eventually(() => bestMatches(root, defaults));
  await setRange(controls.f, 1);
  const after = await eventually(() => bestMatches(root, { ...defaults, f: 1 }));
  for (const id of ['coverage', 'majority']) assert.deepEqual(before.series.find(s => s.id === id).vertices,
    after.series.find(s => s.id === id).vertices, `${id} is independent of the verifier FPR`);
  await setRange(controls.q, 7);
  await root.locator('button[data-ttc-reset]').click();
  for (const [key, value] of Object.entries(defaults)) near(Number(await controls[key].inputValue()), value);
  await eventually(() => bestMatches(root, defaults));
  assert.deepEqual(errors, []);
});

test('effort dial: accuracy per difficulty, the inverse hinge, tokens and cost follow the dial; reset restores', async () => {
  const root = panel('effort-dial'), params = (await paramsFor()).effort;
  const dial = root.locator('input[type=range]'), toggle = root.locator('input[type=checkbox]');
  const initial = Number(await dial.inputValue());
  assert.equal(await toggle.isChecked(), false);
  const xs = Array.from({ length: (params.xMax - params.xMin) * 4 + 1 }, (_, i) => params.xMin + i / 4);
  const api = await page.evaluate(xs => xs.map(x => ({ easy: window.TestTimeCompute.effortAccuracy(x, 'easy'),
    medium: window.TestTimeCompute.effortAccuracy(x, 'medium'), hard: window.TestTimeCompute.effortAccuracy(x, 'hard'),
    inverse: window.TestTimeCompute.inverseAccuracy(x) })), xs);
  xs.forEach((x, i) => {
    for (const id of ['easy', 'medium', 'hard']) near(api[i][id], effortOracle(params, x, id), 1e-9, `${id} at ${x}`);
    near(api[i].inverse, inverseOracle(params, x), 1e-9, `inverse at ${x}`);
  });
  async function match(x, inverse = false) {
    const state = await chartState(root);
    chartContract(state, inverse ? ['easy', 'medium', 'hard', 'inverse'] : ['easy', 'medium', 'hard'], params.xMin, params.xMax, x);
    for (const id of ['easy', 'medium', 'hard']) {
      gridSeries(state, id, u => effortOracle(params, u, id), { min: params.xMin, max: params.xMax, integer: false });
      await percent(root, id, effortOracle(params, x, id));
    }
    if (inverse) {
      const vertices = gridSeries(state, 'inverse', u => inverseOracle(params, u), { min: params.xMin, max: params.xMax, integer: false });
      const peak = Math.max(...vertices.map(v => v.y)), peakIndex = vertices.findIndex(v => v.y === peak);
      assert.ok(peakIndex > 0 && peakIndex < vertices.length - 1, 'inverse peak is interior');
      await percent(root, 'inverse', inverseOracle(params, x));
    }
    await integerMetric(root, 'tokens', 2 ** x);
    await costMetric(root, 2 ** x * params.pricePerMTok / 1e6);
  }
  for (const x of [params.xMin, params.xMax]) { await setRange(dial, x); await eventually(() => match(x)); }
  const ticks = await root.locator('g[data-axis="cost"] text[data-tokens]').evaluateAll(nodes => nodes.map(n => ({ tokens: Number(n.dataset.tokens), text: n.textContent.trim() })));
  assert.ok(ticks.length >= 2, 'cost axis ticks');
  for (const tick of ticks) {
    const expected = tick.tokens * params.pricePerMTok / 1e6;
    near(money(tick.text, false), expected, Math.max(1e-7, expected * 0.02), 'cost axis amount');
  }
  await toggle.check();
  await setRange(dial, 11);
  await eventually(() => match(11, true));
  await root.locator('button[data-ttc-reset]').click();
  assert.equal(Number(await dial.inputValue()), initial); assert.equal(await toggle.isChecked(), false);
  await eventually(() => match(initial));
  assert.deepEqual(errors, []);
});

test('sharpen or expand: the mixtures cross once, and the curves, crossing and readouts follow the slider; reset restores', async () => {
  const root = panel('sharpen-or-expand'), mixtures = (await paramsFor()).mixtures;
  const expected = Array.from({ length: 1024 }, (_, i) => ({ base: mixtureOracle(mixtures.base, i + 1), rl: mixtureOracle(mixtures.rl, i + 1) }));
  assert.ok(expected[0].rl > expected[0].base, 'RL leads at k=1');
  assert.ok(expected.at(-1).base > expected.at(-1).rl, 'base leads at k=1024');
  const signs = expected.map(v => Math.sign(v.base - v.rl)).filter(v => v !== 0);
  assert.equal(signs.slice(1).filter((v, i) => v !== signs[i]).length, 1, 'exactly one sign change');
  const crossing = expected.findIndex(v => v.base >= v.rl) + 1;
  assert.equal(await page.evaluate(() => window.TestTimeCompute.crossingK()), crossing);
  const actual = await page.evaluate(mixtures => Array.from({ length: 1024 }, (_, i) => ({
    base: window.TestTimeCompute.passAtKMixture(mixtures.base, i + 1),
    rl: window.TestTimeCompute.passAtKMixture(mixtures.rl, i + 1),
  })), mixtures);
  actual.forEach((v, i) => { near(v.base, expected[i].base, 1e-9, `base@${i + 1}`); near(v.rl, expected[i].rl, 1e-9, `rl@${i + 1}`); });
  const dial = root.locator('input[type=range]');
  const initial = Number(await dial.inputValue());
  async function match(q) {
    const state = await chartState(root);
    chartContract(state, ['base', 'rl'], 0, 10, q);
    for (const name of ['base', 'rl']) {
      gridSeries(state, name, u => mixtureOracle(mixtures[name], 2 ** Math.round(u)));
      await percent(root, name, mixtureOracle(mixtures[name], 2 ** q));
    }
    await integerMetric(root, 'crossing', crossing);
    assert.equal(state.crossings.length, 1, 'one crossing marker');
    state.crossings[0].forEach(x => near(x, Math.log2(crossing), 0.005, 'crossing log2 position'));
  }
  for (const q of [0, 10]) { await setRange(dial, q); await eventually(() => match(q)); }
  await root.locator('button[data-ttc-reset]').click();
  assert.equal(Number(await dial.inputValue()), initial); await eventually(() => match(initial));
  assert.deepEqual(errors, []);
});
