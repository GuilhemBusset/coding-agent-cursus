import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../../../../tools/html-pages/browser.mjs';
import { repoRoot, sizes, eventually } from '../../../../tools/html-pages/tests/component-helpers.mjs';

/* The attention lab through its public DOM only: no calls to application functions. Numerical
 * oracles read model coordinates and the recorded fixture independently. The inline copy of the
 * fixture is the session pytest's (test_attention_lab.py); layout, accessibility and the no-JS
 * view are the page checker's.
 */
const session = path.join(repoRoot, 'sessions/01-fundamentals');
const file = path.join(session, 'cursus/labs/attention.html');
const recorded = JSON.parse(await readFile(path.join(session, 'cursus/fixtures/attention.json'), 'utf8'));
const norm = value => value.replace(/\s+/g, ' ').trim();
const sum = xs => xs.reduce((a, b) => a + b, 0);
const qx = '[data-attn-qx]';
const qy = '[data-attn-qy]';
const scale = '[data-attn-scale]';
const token = i => `button[data-attn-token][data-index="${i}"]`;
function near(actual, expected, tolerance, message) {
  assert.ok(Number.isFinite(actual) && Number.isFinite(expected), `${message}: finite numbers required`);
  assert.ok(Math.abs(actual - expected) <= tolerance,
    `${message}: got ${actual}, expected ${expected} ± ${tolerance}`);
}
function numbers(text) {
  return [...text.replace(/−/g, '-').matchAll(/[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?/gi)].map(m => +m[0]);
}
function percentages(text) {
  return [...text.matchAll(/([-+]?\d+(?:\.\d+)?)\s*%/g)].map(m => +m[1]);
}
async function setRange(page, selector, value) {
  // Native keyboard operations from the nearer end; no synthetic input.
  const input = page.locator(selector);
  const [min, max, step] = await input.evaluate(el => [+el.min, +el.max, +el.step]);
  const low = Math.round((value - min) / step), high = Math.round((max - value) / step);
  await input.focus();
  await input.press(low <= high ? 'Home' : 'End');
  for (let i = 0; i < Math.min(low, high); i++) await input.press(low <= high ? 'ArrowRight' : 'ArrowLeft');
  near(+(await input.inputValue()), value, 1e-8, selector);
}
async function setToy(page, x, y, s) {
  await setRange(page, qx, x);
  await setRange(page, qy, y);
  await setRange(page, scale, s);
}

let browser, page;
const errors = [];
before(async () => {
  browser = await chromium.launch();
  const context = await browser.newContext({ viewport: sizes[0], offline: true });
  await context.route(/^(https?|wss?):/i, route => { errors.push(`remote request: ${route.request().url()}`); return route.abort(); });
  page = await context.newPage();
  page.setDefaultTimeout(4000);
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(pathToFileURL(file).href);
});
after(() => browser?.close());

async function toySnapshot(page) {
  return page.locator('#toy').evaluate(root => {
    // Read actual SVG geometry in CSS pixels, including all SVG/CSS transforms.
    function position(el) {
      const circle = el.matches('circle, ellipse') ? el : el.querySelector('circle, ellipse');
      const shape = circle || el;
      const b = shape.getBBox();
      const local = circle ? { x: circle.cx.baseVal.value, y: circle.cy.baseVal.value }
        : { x: b.x + b.width / 2, y: b.y + b.height / 2 };
      const p = new DOMPoint(local.x, local.y).matrixTransform(shape.getScreenCTM());
      return { px: p.x, py: p.y };
    }
    const all = selector => [...root.querySelectorAll(selector)];
    const marks = selector => all(selector).map(el => ({
      i: Number(el.dataset.index), x: Number(el.dataset.x), y: Number(el.dataset.y),
      hasCoordinates: el.hasAttribute('data-x') && el.hasAttribute('data-y'),
      ...position(el),
      label: el.getAttribute('aria-label') || el.textContent || el.parentElement.textContent,
    }));
    const plots = [...root.querySelectorAll('svg')].filter(svg => svg.querySelector('[data-attn-key], [data-attn-value]'));
    return {
      q: ['qx', 'qy'].map(k => Number(root.querySelector(`[data-attn-${k}]`).value)),
      s: Number(root.querySelector('[data-attn-scale]').value),
      keys: marks('[data-attn-key]'), values: marks('[data-attn-value]'),
      query: marks('[data-attn-query]'), output: marks('[data-attn-output]'),
      weights: all('[data-attn-weight]').map((el, i) => ({
        i: el.hasAttribute('data-index') ? Number(el.dataset.index) : i, text: el.textContent,
      })),
      discs: all('circle[data-attn-mass]').map((el, i) => {
        const owner = el.closest('[data-index]');
        const matrix = el.getScreenCTM();
        return { i: owner ? Number(owner.dataset.index) : i,
          area: el.r.baseVal.value ** 2 * Math.abs(matrix.a * matrix.d - matrix.b * matrix.c),
          ...position(el) };
      }),
      readout: root.querySelector('[data-attn-output-readout]')?.textContent,
      plots: plots.map(svg => ({
        kind: svg.querySelector('[data-attn-key]') ? 'keys' : 'values',
        ticks: [...svg.querySelectorAll('[data-attn-tick]')].map(el => {
          let p;
          if (el.matches('text')) {
            p = new DOMPoint(el.x.baseVal[0].value, el.y.baseVal[0].value).matrixTransform(el.getScreenCTM());
          } else {
            const b = position(el); p = { x: b.px, y: b.py };
          }
          return { axis: el.dataset.axis, value: Number(el.dataset.value), px: p.x, py: p.y,
            visible: getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none' };
        }),
      })),
    };
  });
}
function indexed(items, n, label) {
  assert.equal(items.length, n, `${label} count`);
  assert.deepEqual(items.map(x => x.i).sort((a, b) => a - b), Array.from({ length: n }, (_, i) => i), `${label} indices`);
  return [...items].sort((a, b) => a.i - b.i);
}
function oracle(state) {
  const keys = indexed(state.keys, 4, 'keys');
  const values = indexed(state.values, 4, 'values');
  const z = keys.map(k => state.s * (state.q[0] * k.x + state.q[1] * k.y));
  const exp = z.map(x => Math.exp(x - Math.max(...z)));
  const w = exp.map(x => x / sum(exp));
  return { w, o: [sum(values.map((v, i) => v.x * w[i])), sum(values.map((v, i) => v.y * w[i]))] };
}
function mapping(plot, axis) {
  const ticks = plot.ticks.filter(t => t.axis === axis).sort((a, b) => a.value - b.value);
  assert.ok(ticks.length >= 2 && ticks.every(t => t.visible), `visible ${axis} ticks`);
  const first = ticks[0], last = ticks.at(-1), coord = axis === 'x' ? 'px' : 'py';
  assert.ok(last.value > first.value, 'distinct tick values');
  const slope = (last[coord] - first[coord]) / (last.value - first.value);
  assert.ok(axis === 'x' ? slope > 0 : slope < 0, 'Cartesian axis orientation');
  const map = value => first[coord] + (value - first.value) * slope;
  for (const tick of ticks) near(tick[coord], map(tick.value), 1.5, 'linear tick positions');
  return map;
}
function assertToy(state) {
  const { w, o } = oracle(state);
  const keys = indexed(state.keys, 4, 'keys'), values = indexed(state.values, 4, 'values');
  const weights = indexed(state.weights, 4, 'weight readouts');
  const discs = indexed(state.discs, 4, 'mass discs');
  for (const marks of [keys, values]) {
    assert.equal(new Set(marks.map(p => `${p.x},${p.y}`)).size, 4, 'four distinct points');
    for (const p of marks) {
      assert.ok(p.hasCoordinates && Math.abs(p.x) <= 2 && Math.abs(p.y) <= 2, 'model coordinates in [-2,2]');
    }
  }
  assert.ok(values.every((v, i) => v.x !== keys[i].x || v.y !== keys[i].y), 'values differ from paired keys');
  const shown = weights.map((v, i) => {
    const p = percentages(v.text);
    assert.equal(p.length, 1, 'one percentage per toy weight');
    near(p[0], 100 * w[i], 0.051, `weight ${i}`);
    return p[0] / 100;
  });
  near(sum(shown), 1, 0.0021, 'rounded displayed measure sums to one');
  const factor = discs[0].area / w[0];
  assert.ok(factor > 0, 'visible mass');
  discs.forEach((d, i) => {
    near(d.area / w[i], factor, factor * 0.015, `disc area proportional to weight ${i}`);
    near(d.px, values[i].px, 1.5, 'mass at value x');
    near(d.py, values[i].py, 1.5, 'mass at value y');
  });
  assert.equal(state.query.length, 1); assert.equal(state.output.length, 1);
  const q = state.query[0], out = state.output[0];
  assert.ok(q.hasCoordinates && out.hasCoordinates);
  near(q.x, state.q[0], 1e-6, 'query x sync'); near(q.y, state.q[1], 1e-6, 'query y sync');
  near(out.x, o[0], 1e-5, 'output model x'); near(out.y, o[1], 1e-5, 'output model y');
  const displayedOutput = numbers(state.readout || '');
  assert.equal(displayedOutput.length, 2, 'output readout is an (x,y) pair');
  displayedOutput.forEach((v, i) => near(v, o[i], 0.0051, 'output rounded to two decimals'));
  assert.equal(state.plots.length, 2, 'separate key and value SVG plots');
  for (const plot of state.plots) {
    const mx = mapping(plot, 'x'), my = mapping(plot, 'y');
    for (const p of plot.kind === 'keys' ? [...keys, q] : [...values, out]) {
      near(p.px, mx(p.x), 1.5, 'plotted x uses visible axes');
      near(p.py, my(p.y), 1.5, 'plotted y uses visible axes');
    }
  }
  near(out.px, sum(values.map((v, i) => v.px * w[i])), 1.5, 'rendered expectation x');
  near(out.py, sum(values.map((v, i) => v.py * w[i])), 1.5, 'rendered expectation y');
  return { w, o };
}
async function checkToy(page) {
  let state;
  await eventually(async () => { state = await toySnapshot(page); assertToy(state); }, 'toy numerical and geometric oracle');
  return state;
}

async function arcSnapshot(page) {
  return page.locator('#gpt2').evaluate(root => {
    const chips = [...root.querySelectorAll('button[data-attn-token]')].map(el => {
      const b = el.getBoundingClientRect();
      return { i: Number(el.dataset.index), text: el.textContent, pressed: el.getAttribute('aria-pressed'),
        x: b.x + b.width / 2, y: b.y + b.height / 2, top: b.top, bottom: b.bottom };
    });
    const arcs = [...root.querySelectorAll('path[data-attn-arc]')].map(el => {
      const length = el.getTotalLength(), transform = el.getScreenCTM();
      const start = el.getPointAtLength(0).matrixTransform(transform);
      const end = el.getPointAtLength(length).matrixTransform(transform);
      const css = getComputedStyle(el), box = el.getBBox();
      return { q: Number(el.dataset.query), k: Number(el.dataset.key), w: Number(el.dataset.weight),
        hasWeight: el.hasAttribute('data-weight'), d: el.getAttribute('d'), length,
        start: { x: start.x, y: start.y }, end: { x: end.x, y: end.y },
        width: parseFloat(css.strokeWidth), opacity: Number(css.opacity) * Number(css.strokeOpacity),
        stroke: css.stroke, visible: css.display !== 'none' && css.visibility !== 'hidden',
        height: box.height, extent: box.width };
    });
    return { chips, arcs, layer: Number(root.querySelector('[data-attn-layer]').value),
      head: Number(root.querySelector('[data-attn-head]').value),
      readout: root.querySelector('[data-attn-readout]')?.innerText };
  });
}
function assertArcs(state, q, layer, head) {
  assert.equal(state.layer, layer); assert.equal(state.head, head);
  assert.deepEqual(state.chips.filter(c => c.pressed === 'true').map(c => c.i), [q], 'one selected query');
  const chips = indexed(state.chips, recorded.tokens.length, 'tokens');
  const arcs = [...state.arcs].sort((a, b) => a.k - b.k);
  assert.deepEqual(arcs.map(a => a.k), Array.from({ length: q + 1 }, (_, i) => i), 'all and only causal keys, including self');
  for (const arc of arcs) {
    assert.equal(arc.q, q); assert.ok(arc.hasWeight);
    near(arc.w, recorded.weights[layer][head][q][arc.k] / recorded.scale, 0.5 / recorded.scale, 'raw quantized weight; no softmax or normalization');
    assert.ok(arc.d?.trim() && arc.length > 0 && arc.visible, 'rendered nonempty path');
    assert.ok(arc.stroke && arc.stroke !== 'none' && arc.width > 0 && arc.opacity >= 0, 'stroke encodes weight');
    // Either direction is legitimate: query→key or key→query.
    const endpoints = [[arc.start, arc.end], [arc.end, arc.start]];
    assert.ok(endpoints.some(([a, b]) => Math.abs(a.x - chips[q].x) <= 2 && Math.abs(b.x - chips[arc.k].x) <= 2 &&
      a.y >= chips[q].top - 2 && a.y <= chips[q].bottom + 2 && b.y >= chips[arc.k].top - 2 && b.y <= chips[arc.k].bottom + 2),
    `arc ${q}→${arc.k} endpoints anchored to horizontal chip centres`);
    if (arc.k === q) assert.ok(arc.height > 2 && arc.extent > 2, 'self-attention is a visible loop, not a zero-length path');
  }
  const ordered = [...arcs].sort((a, b) => a.w - b.w);
  for (let i = 1; i < ordered.length; i++) {
    assert.ok(ordered[i].width + 1e-6 >= ordered[i - 1].width, 'stroke width non-decreasing with weight');
    assert.ok(ordered[i].opacity + 1e-6 >= ordered[i - 1].opacity, 'opacity non-decreasing with weight');
  }
  if (ordered.length > 1 && ordered.at(-1).w > ordered[0].w) {
    assert.ok(ordered.at(-1).width > ordered[0].width, 'width conveys the measure');
    assert.ok(ordered.at(-1).opacity > ordered[0].opacity, 'opacity conveys the measure');
  }
  const readout = norm(state.readout || '');
  assert.ok(readout.includes(recorded.tokens[q].text.trim()), 'readout names query');
  // Percent or fractional readouts are both valid. Only the maximum must be first;
  // the remaining entries may follow token order or descending weight.
  const expected = recorded.weights[layer][head][q].slice(0, q + 1).map(x => x / recorded.scale).sort((a, b) => b - a);
  const percent = percentages(readout);
  const actual = percent.length ? percent.map(x => x / 100)
    : [...readout.matchAll(/\b(?:0(?:\.\d+)?|1(?:\.0+)?)\b/g)].map(m => +m[0]);
  assert.equal(actual.length, expected.length, 'readout lists every causal weight, top key first');
  near(actual[0], expected[0], 0.0051, 'readout starts with maximum weight');
  [...actual].sort((a, b) => b - a).forEach((value, i) => near(value, expected[i], 0.0051, 'readout weight'));
  const topWeight = Math.max(...recorded.weights[layer][head][q].slice(0, q + 1));
  const topKeys = Array.from({ length: q + 1 }, (_, i) => i).filter(i => recorded.weights[layer][head][q][i] === topWeight);
  const firstNumber = percent.length ? readout.search(/\d+(?:\.\d+)?\s*%/) : readout.search(/\b(?:0(?:\.\d+)?|1(?:\.0+)?)\b/);
  const prefix = readout.slice(0, firstNumber);
  assert.ok(topKeys.some(i => prefix.includes(recorded.tokens[i].text.trim())), 'first weight names a maximum-weight key');
}
async function checkArcs(page, q, layer, head) {
  await eventually(async () => assertArcs(await arcSnapshot(page), q, layer, head), `arcs q=${q}, layer=${layer}, head=${head}`);
}
async function chooseHead(page, layer, head) {
  await page.locator('[data-attn-layer]').selectOption(String(layer));
  await page.locator('[data-attn-head]').selectOption(String(head));
}

test('toy: the sliders drive the softmax weights, the expectation and the plot; zero scale is uniform; reset restores', async () => {
  const initial = await checkToy(page);
  near(initial.s, 1 / Math.sqrt(2), 0.0051, 'default d=2 score multiplier');
  for (const [x, y, s] of [[1.35, -0.65, 0.43], [-1.15, 1.7, 1.37], [2, -2, 2]]) {
    await setToy(page, x, y, s);
    const state = await checkToy(page);
    assert.deepEqual(state.keys.map(k => [k.x, k.y]), initial.keys.map(k => [k.x, k.y]), 'keys remain fixed');
    assert.deepEqual(state.values.map(v => [v.x, v.y]), initial.values.map(v => [v.x, v.y]), 'values remain fixed');
    const text = await page.locator('#toy').innerText();
    assert.ok(numbers(text).some(value => Math.abs(value - s) <= 0.0051), 'visible current scale multiplier');
    const dimensions = [...text.matchAll(/\bd\s*(?:=|≈|~|:)\s*(\d+(?:\.\d+)?)/g)].map(m => +m[1]);
    assert.ok(dimensions.some(d => Math.abs(d - 1 / (s * s)) <= Math.max(0.011, 0.01 / (s * s))), 'visible equivalent dimension d=1/s²');
  }
  const sharp = assertToy(await toySnapshot(page)).w;
  assert.ok(Math.max(...sharp) > 0.25, 'a large scale sharpens the weights');
  await setRange(page, scale, 0);
  await checkToy(page);
  assert.doesNotMatch(await page.locator('#toy').innerText(), /\bNaN\b|\bInfinity\b/);
  assertToy(await toySnapshot(page)).w.forEach(w => near(w, 0.25, 1e-12, 'uniform at zero scale'));
  await page.locator('[data-attn-reset]').click();
  const reset = await checkToy(page);
  assert.deepEqual(reset.q, initial.q); assert.equal(reset.s, initial.s);
  assert.deepEqual(errors, []);
});

test('toy: dragging the query handle moves the query and the sliders follow', async () => {
  const handle = page.locator('[data-attn-query]');
  await handle.scrollIntoViewIfNeeded();
  const before = await checkToy(page);
  const plot = before.plots.find(p => p.kind === 'keys');
  const target = Math.abs(before.q[0] - 1.1) < 0.1 ? [-1.25, 0.9] : [1.1, -0.8];
  const x = mapping(plot, 'x')(target[0]), y = mapping(plot, 'y')(target[1]);
  await page.mouse.move(before.query[0].px, before.query[0].py);
  await page.mouse.down();
  await page.mouse.move(x, y, { steps: 8 });
  await page.mouse.up();
  const dragged = await checkToy(page);
  near(dragged.q[0], target[0], 0.051, 'drag changes qx');
  near(dragged.q[1], target[1], 0.051, 'drag changes qy');
  await page.locator('[data-attn-reset]').click();
  assert.deepEqual(errors, []);
});

test('GPT-2: the recorded sentence and every layer and head are offered; the default head is the recorded maximum', async () => {
  const chips = await page.locator('#gpt2 button[data-attn-token]').evaluateAll(els => els.map(el => [el.dataset.index, el.innerText]));
  assert.deepEqual(chips.map(([i, text]) => [i, norm(text)]), recorded.tokens.map((t, i) => [String(i), norm(t.text)]));
  for (const [selector, n] of [['[data-attn-layer]', recorded.layers], ['[data-attn-head]', recorded.heads]]) {
    const values = await page.locator(`select${selector} option`).evaluateAll(els => els.map(el => el.value));
    assert.deepEqual(values, Array.from({ length: n }, (_, i) => String(i)));
  }
  const text = await page.locator('#gpt2').innerText();
  for (const model of recorded.meta.models) assert.ok(text.includes(model.id) && text.includes(model.revision), 'model and pinned revision');
  let best = { layer: 0, head: 0, weight: -1 };
  for (let layer = 0; layer < recorded.layers; layer++) {
    for (let head = 0; head < recorded.heads; head++) {
      const weight = recorded.weights[layer][head][recorded.focus][recorded.referent];
      if (weight > best.weight) best = { layer, head, weight };
    }
  }
  await checkArcs(page, recorded.focus, best.layer, best.head);
  assert.deepEqual(errors, []);
});

test('GPT-2: layer and head choices draw the recorded weights, and hover, focus and click select the query', async () => {
  for (const [layer, head] of [[0, 0], [recorded.layers - 1, recorded.heads - 1], [Math.floor(recorded.layers / 2), Math.floor(recorded.heads / 2)]]) {
    const query = (await arcSnapshot(page)).chips.find(c => c.pressed === 'true').i;
    await chooseHead(page, layer, head);
    await checkArcs(page, query, layer, head);
  }
  const [layer, head] = [Math.floor(recorded.layers / 2), Math.floor(recorded.heads / 2)];
  for (const [q, method] of [[0, 'hover'], [recorded.tokens.length - 1, 'focus'], [recorded.referent, 'click'], [recorded.focus, 'click']]) {
    // Each input method on its own: focus elsewhere and move the pointer away first.
    await page.locator(token((q + 1) % recorded.tokens.length)).focus();
    await page.mouse.move(0, 0);
    const chip = page.locator(token(q));
    if (method === 'click') await chip.dispatchEvent('click'); // the click handler alone, not focus or pointerenter
    else await chip[method]();
    await checkArcs(page, q, layer, head);
  }
  assert.deepEqual(errors, []);
});
