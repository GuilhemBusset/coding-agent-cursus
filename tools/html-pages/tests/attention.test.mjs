import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { chromium } from '../browser.mjs';
import { openPage, repoRoot, sizes, eventually, assertCollected } from './component-helpers.mjs';

/* Issue 39's public DOM contract only: no calls to application functions.
 * Numerical oracles read model coordinates and fixture bytes independently.
 * Vertical arc anchoring is deliberately free (chip centre or edge); the design
 * specifies horizontal centres. Review quality remains an agent obligation;
 * the evidence checks bind that review to the actual page and quoted notes.
 */
const session = path.join(repoRoot, 'sessions/01-fundamentals');
const file = path.join(session, 'cursus/labs/attention.html');
const reviewFile = path.join(session, 'cursus/labs/attention/review.md');
const fixtureBytes = await readFile(path.join(session, 'cursus/fixtures/attention.json'));
const recorded = JSON.parse(fixtureBytes);
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const norm = value => value.replace(/\s+/g, ' ').trim();
const sum = xs => xs.reduce((a, b) => a + b, 0);
const qx = '[data-attn-qx]';
const qy = '[data-attn-qy]';
const scale = '[data-attn-scale]';
const token = i => `button[data-attn-token][data-index="${i}"]`;
const pageFor = (t, options = {}) => openPage(t, chromium, { file, offline: true, ...options });
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
async function visible(locator) {
  assert.equal(await locator.count(), 1, `one ${locator}`);
  assert.equal(await locator.isVisible(), true, `visible ${locator}`);
}
async function setRange(page, selector, value) {
  // Native keyboard operations, including boundary values; no synthetic input.
  const input = page.locator(selector);
  const min = +(await input.getAttribute('min'));
  const step = +(await input.getAttribute('step'));
  await input.focus();
  await input.press('Home');
  const n = Math.round((value - min) / step);
  for (let i = 0; i < n; i++) await input.press('ArrowRight');
  near(+(await input.inputValue()), value, 1e-8, selector);
}
async function setToy(page, x, y, s) {
  await setRange(page, qx, x);
  await setRange(page, qy, y);
  await setRange(page, scale, s);
}

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
      assert.ok(norm(p.label), 'point has a label');
    }
  }
  assert.ok(values.every((v, i) => v.x !== keys[i].x || v.y !== keys[i].y), 'values differ from paired keys');
  const shown = weights.map((v, i) => {
    const p = percentages(v.text);
    assert.equal(p.length, 1, 'one percentage per toy weight');
    assert.match(v.text, /\d+\.\d\s*%/, 'weight shown to one decimal');
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

function reviewSection(markdown, heading) {
  const lines = markdown.split('\n');
  const start = lines.findIndex(line => /^#{1,6}\s/.test(line) && heading.test(line));
  assert.ok(start >= 0, `review heading ${heading}`);
  const level = lines[start].match(/^#+/)[0].length;
  const rest = lines.slice(start + 1);
  const end = rest.findIndex(line => new RegExp(`^#{1,${level}}\\s`).test(line));
  return (end < 0 ? rest : rest.slice(0, end)).join('\n');
}

test('D1: self-contained lab structure and registered acceptance suite', async t => {
  const page = await pageFor(t);
  assert.equal(await page.locator('html').getAttribute('data-design-system'), 'cursus');
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'lab');
  assert.equal(await page.locator('section[data-panel]').count(), 2);
  for (const id of ['toy', 'gpt2']) await visible(page.locator(`section#${id}[data-panel]`));
  assert.equal(await page.locator('script[src], script[type="module"]').count(), 0);
  for (const source of await page.locator('script:not([type="application/json"])').allTextContents()) {
    assert.doesNotMatch(source, /\bfetch\s*\(|\bXMLHttpRequest\b/, 'inline data needs no runtime fetch');
  }
  assert.equal(await page.locator('[data-lab], [data-reset]').count(), 0);
  assert.equal(await page.locator('*').evaluateAll(els => els.some(el => [...el.attributes].some(a => a.name.startsWith('data-budget')))), false);
  await assertCollected('attention');
  for (const kind of ['permutation', 'multi-head']) {
    const note = page.locator(`[data-attn-note="${kind}"]`);
    await visible(note);
    assert.equal(await note.evaluate(el => !!el.closest('section:not([data-panel])')), true, 'notes outside interactive panels');
  }
});

test('D2: controls, formula and independent softmax/expectation oracle across nontrivial states', async t => {
  const page = await pageFor(t);
  for (const [selector, min, max, step] of [[qx, -2, 2, 0.05], [qy, -2, 2, 0.05], [scale, 0, 2, 0.01]]) {
    const input = page.locator(selector);
    await visible(input);
    assert.equal(await input.getAttribute('type'), 'range');
    assert.equal(+(await input.getAttribute('min')), min);
    assert.equal(+(await input.getAttribute('max')), max);
    assert.equal(+(await input.getAttribute('step')), step);
    assert.ok(await input.evaluate(el => [...el.labels].some(label => label.textContent.trim()) || el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')), 'named range');
  }
  const callout = page.locator('#toy .callout[data-illustrative]');
  await visible(callout); assert.match(await callout.innerText(), /illustrat/i);
  const formula = page.locator('[data-attn-formula]');
  await visible(formula);
  const formulaText = norm(await formula.innerText());
  assert.match(formulaText, /softmax|exp/i);
  assert.match(formulaText, /Σ|∑|sum|expect/i);
  assert.match(await page.locator('#toy').innerText(), /1\s*\/\s*√\s*d|1\s*\/\s*sqrt\s*\(?d/i);
  const initial = await checkToy(page);
  near(initial.s, 1 / Math.sqrt(2), 0.0051, 'default d=2 score multiplier');
  for (const [x, y, s] of [[0, 0, 0.71], [1.35, -0.65, 0.43], [-1.15, 1.7, 1.37], [2, -2, 2], [-2, 2, 0]]) {
    await setToy(page, x, y, s);
    const state = await checkToy(page);
    assert.deepEqual(state.keys.map(k => [k.x, k.y]), initial.keys.map(k => [k.x, k.y]), 'keys remain fixed');
    assert.deepEqual(state.values.map(v => [v.x, v.y]), initial.values.map(v => [v.x, v.y]), 'values remain fixed');
    if (s === 0) {
      const text = await page.locator('#toy').innerText();
      assert.doesNotMatch(text, /\bNaN\b|\bInfinity\b/);
      assert.match(text, /d\s*(?:→|->)\s*∞/);
      assert.match(text, /uniform average/i);
    } else {
      // s and equivalent d must be visible; output/labels are not tied to an extra selector.
      const text = await page.locator('#toy').innerText();
      assert.ok(numbers(text).some(value => Math.abs(value - s) <= 0.0051), 'visible current scale multiplier');
      const dimensions = [...text.matchAll(/\bd\s*(?:=|≈|~|:)\s*(\d+(?:\.\d+)?)/g)].map(m => +m[1]);
      assert.ok(dimensions.some(d => Math.abs(d - 1 / (s * s)) <= Math.max(0.011, 0.01 / (s * s))),
        'visible equivalent dimension d=1/s²');
    }
  }
  await setToy(page, 1.35, -0.65, 0);
  const uniform = assertToy(await toySnapshot(page)).w;
  uniform.forEach(w => near(w, 0.25, 1e-12, 'uniform at zero scale'));
  await setRange(page, scale, 2);
  const sharp = assertToy(await toySnapshot(page)).w;
  assert.ok(Math.max(...sharp) >= Math.max(...uniform));
  await page.locator('[data-attn-reset]').click();
  const reset = await checkToy(page);
  assert.deepEqual(reset.q, initial.q); assert.equal(reset.s, initial.s);
});

for (const viewport of [sizes[0], sizes[2]]) {
  test(`D2: real pointer drag and slider synchronization at ${viewport.width}px`, async t => {
    const page = await pageFor(t, { viewport });
    const handle = page.locator('[data-attn-query]');
    await handle.scrollIntoViewIfNeeded();
    const before = await checkToy(page);
    const plot = before.plots.find(p => p.kind === 'keys');
    const target = Math.abs(before.q[0] - 1.1) < 0.1 ? [-1.25, 0.9] : [1.1, -0.8];
    const x = mapping(plot, 'x')(target[0]), y = mapping(plot, 'y')(target[1]);
    const start = before.query[0];
    const captures = [];
    await page.exposeFunction('acceptancePointerCapture', value => captures.push(value));
    await handle.evaluate(el => el.addEventListener('gotpointercapture', () => window.acceptancePointerCapture(true), { once: true }));
    assert.equal(await handle.evaluate(el => getComputedStyle(el).touchAction), 'none');
    await page.mouse.move(start.px, start.py);
    await page.mouse.down();
    await page.mouse.move(x, y, { steps: 8 });
    await page.mouse.up();
    const dragged = await checkToy(page);
    near(dragged.q[0], target[0], 0.051, 'drag changes qx');
    near(dragged.q[1], target[1], 0.051, 'drag changes qy');
    assert.notDeepEqual(dragged.q, before.q);
    await eventually(() => assert.ok(captures.length, 'handle captures pointer during drag'));
    for (const selector of [qx, qy, scale]) {
      const input = page.locator(selector), old = +(await input.inputValue());
      await input.focus(); await input.press('ArrowRight');
      near(+(await input.inputValue()), old + +(await input.getAttribute('step')), 1e-8, 'keyboard step');
      await checkToy(page);
    }
    const motion = await page.locator('#toy svg *').evaluateAll(els => els.some(el => {
      const s = getComputedStyle(el);
      return s.transitionDuration.split(',').some(v => parseFloat(v) > 0) || s.animationName !== 'none';
    }));
    assert.equal(motion, false, 'toy has no transitions or animations');
  });
}

test('D3: verbatim fixture, token order, complete layer/head choices and provenance', async t => {
  const page = await pageFor(t);
  const inline = page.locator('script#attention-data[type="application/json"]');
  assert.equal(await inline.count(), 1);
  assert.equal(await inline.getAttribute('data-sha256'), sha256(fixtureBytes));
  assert.deepEqual(JSON.parse(await inline.textContent()), recorded);
  assert.equal((await inline.textContent()).trim(), fixtureBytes.toString('utf8').trim());
  const chips = page.locator('#gpt2 button[data-attn-token]');
  assert.equal(await chips.count(), recorded.tokens.length);
  for (let i = 0; i < recorded.tokens.length; i++) {
    const chip = chips.nth(i);
    assert.equal(await chip.getAttribute('data-index'), String(i));
    assert.equal(norm(await chip.innerText()), norm(recorded.tokens[i].text));
  }
  for (const [selector, n] of [['[data-attn-layer]', recorded.layers], ['[data-attn-head]', recorded.heads]]) {
    const select = page.locator(`select${selector}`);
    await visible(select);
    assert.ok(await select.evaluate(el => [...el.labels].some(label => label.textContent.trim()) || el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')), 'named select');
    const options = await select.locator('option').evaluateAll(els => els.map(el => [el.value, el.textContent.trim()]));
    assert.deepEqual(options.map(o => o[0]), Array.from({ length: n }, (_, i) => String(i)));
    options.forEach((o, i) => assert.deepEqual(numbers(o[1]), [i + 1], 'human labels are 1-based'));
  }
  const text = await page.locator('#gpt2').innerText();
  for (const model of recorded.meta.models) {
    assert.ok(text.includes(model.id), 'model id'); assert.ok(text.includes(model.revision), 'full pinned revision');
  }
  assert.ok(text.includes(recorded.meta.date), 'export date');
  assert.match(text, /round|quantiz/i); assert.match(text, /1\s*\/\s*255/);
  assert.match(text, /differ|not exactly|may not|slight/i);
  assert.equal(await page.locator('#gpt2 [data-illustrative]').count(), 0, 'recorded data is not illustrative');
  await visible(page.locator('#gpt2 a[href="../fixtures/attention.json"]'));
  const readme = await readFile(path.join(session, 'README.md'), 'utf8');
  const regeneration = reviewSection(readme, /regenerat.*fixture|fixture.*regenerat/i);
  assert.match(regeneration, /attention\.html/); assert.match(regeneration, /data-sha256/);
  assert.match(regeneration, /attention\.test\.mjs/);
});

test('D3: fixture-derived causal arcs at every layer and head, with query preserved', async t => {
  const page = await pageFor(t);
  await page.locator(token(recorded.focus)).hover();
  for (let layer = 0; layer < recorded.layers; layer++) {
    for (let head = 0; head < recorded.heads; head++) {
      await chooseHead(page, layer, head);
      await checkArcs(page, recorded.focus, layer, head);
    }
  }
});

for (const viewport of [sizes[0], sizes[2]]) {
  test(`D3: hover, focus and click update arcs for all query tokens at ${viewport.width}px`, async t => {
    const page = await pageFor(t, { viewport });
    const pairs = [[0, 0], [Math.floor(recorded.layers / 2), Math.floor(recorded.heads / 2)], [recorded.layers - 1, recorded.heads - 1]];
    for (const [layer, head] of pairs) {
      const previousQuery = (await arcSnapshot(page)).chips.find(c => c.pressed === 'true').i;
      await chooseHead(page, layer, head);
      await checkArcs(page, previousQuery, layer, head);
      for (let q = 0; q < recorded.tokens.length; q++) {
        // Test each input method independently; focusing first must not mask broken click/hover handlers.
        for (const method of ['hover', 'focus', 'click']) {
          const other = (q + 1) % recorded.tokens.length;
          await page.locator(token(other)).focus();
          await page.mouse.move(0, 0);
          const chip = page.locator(token(q));
          if (method === 'click') {
            // dispatch click alone proves its handler rather than incidental focus/pointerenter.
            await chip.dispatchEvent('click');
          } else await chip[method]();
          await checkArcs(page, q, layer, head);
          if (method === 'click') {
            await chip.click(); // Also prove the real pointer target is unobstructed.
            await checkArcs(page, q, layer, head);
          }
        }
      }
    }
  });
}

test('Default head maximizes the recorded focus-to-referent weight, with layer-major ties', async t => {
  const page = await pageFor(t);
  let best = { layer: 0, head: 0, weight: -1 };
  for (let layer = 0; layer < recorded.layers; layer++) {
    for (let head = 0; head < recorded.heads; head++) {
      const weight = recorded.weights[layer][head][recorded.focus][recorded.referent];
      if (weight > best.weight) best = { layer, head, weight };
    }
  }
  await checkArcs(page, recorded.focus, best.layer, best.head);
});

test('D4: two visible single-sentence notes, quoted and reviewed against the final HTML', async t => {
  const page = await pageFor(t);
  const review = await readFile(reviewFile, 'utf8');
  assert.ok(review.includes(sha256(await readFile(file))), 'review bound to final page sha256');
  const prose = reviewSection(review, /notes|prose/i);
  assert.equal(await page.locator('[data-attn-note]').count(), 2);
  const sentences = [];
  for (const kind of ['permutation', 'multi-head']) {
    const note = page.locator(`[data-attn-note="${kind}"]`);
    await visible(note);
    const text = norm(await note.innerText());
    // These guard the agreed topics; correctness is established by the bound prose review below.
    for (const term of kind === 'permutation' ? [/position/i, /causal/i, /permut/i]
      : [/query/i, /key/i, /value/i, /projection/i]) assert.match(text, term);
    const segments = [...new Intl.Segmenter('en', { granularity: 'sentence' }).segment(text)];
    assert.equal(segments.length, 1, 'one sentence per note');
    assert.ok(norm(prose).includes(text), 'notes review quotes the actual sentence verbatim');
    sentences.push(text);
  }
  // Content accuracy is the named prose review, not a keyword score or frozen wording.
  let explanation = norm(prose);
  for (const sentence of sentences) explanation = explanation.replace(sentence, '');
  assert.ok(explanation.split(/\s+/).filter(Boolean).length >= 25, 'review explains accuracy beyond merely quoting the notes');
  const views = reviewSection(review, /screenshot|visual|views/i);
  for (const mode of [/desktop/i, /laptop/i, /mobile/i, /no[ -]?(?:js|javascript)/i, /print/i, /reduced[ -]motion/i,
    /drag(?:ged|ging)?.*query|query.*drag/i, /chang(?:ed|ing)?.*head|head.*chang/i]) assert.match(views, mode);
});

test('A1: Tab reaches each enabled control in DOM order with visible focus; keyboard drives both panels', async t => {
  const page = await pageFor(t);
  const selectors = '#toy input[type="range"], #toy button, #gpt2 select, #gpt2 button';
  const controls = page.locator(selectors);
  const count = await controls.count();
  assert.equal(count, 3 + 1 + 2 + recorded.tokens.length, 'three ranges, reset, two selects and all tokens');
  for (const control of await controls.all()) assert.equal(await control.isEnabled(), true);
  await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
  const seen = [];
  for (let step = 0; step < count + 30 && seen.length < count; step++) {
    await page.keyboard.press('Tab');
    const focus = await controls.evaluateAll(els => {
      const i = els.indexOf(document.activeElement);
      if (i < 0) return { i };
      const el = els[i], css = getComputedStyle(el), b = el.getBoundingClientRect();
      const outline = parseFloat(css.outlineWidth) > 0 && css.outlineStyle !== 'none' && css.outlineColor !== 'transparent' && !css.outlineColor.endsWith(', 0)');
      const shadow = css.boxShadow !== 'none' && !css.boxShadow.startsWith('rgba(0, 0, 0, 0)');
      return { i, ring: outline || shadow, shown: b.width > 0 && b.height > 0 && b.bottom > 0 && b.top < innerHeight };
    });
    if (focus.i >= 0) {
      assert.equal(focus.i, seen.length, 'Tab order follows controls in document order');
      assert.ok(focus.ring && focus.shown, `visible keyboard focus on control ${focus.i}`);
      seen.push(focus.i);
    }
  }
  assert.equal(seen.length, count, 'all controls reachable without pointer');
  await setToy(page, -0.85, 1.25, 1.23);
  await checkToy(page);
  const reset = page.locator('[data-attn-reset]');
  await reset.focus(); await reset.press('Enter'); await checkToy(page);
  const layer = page.locator('[data-attn-layer]'), head = page.locator('[data-attn-head]');
  await layer.focus(); await layer.press('Home'); await layer.press('ArrowDown'); await layer.press('Enter');
  await head.focus(); await head.press('End'); await head.press('ArrowUp'); await head.press('Enter');
  assert.equal(+(await layer.inputValue()), 1);
  assert.equal(+(await head.inputValue()), recorded.heads - 2);
  const q = recorded.tokens.length - 1;
  await page.locator(token(q)).focus(); await page.locator(token(q)).press('Space');
  await checkArcs(page, q, 1, recorded.heads - 2);
});

test('A1: no-JavaScript view preserves readable explanation, static measure and recorded sentence', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  for (const id of ['toy', 'gpt2']) await visible(page.locator(`#${id}`));
  await visible(page.locator('[data-attn-formula]'));
  await visible(page.locator('[data-attn-output-readout]'));
  const toy = await page.locator('#toy').innerText();
  assert.match(toy, /illustrat/i); assert.ok(percentages(toy).length >= 4, 'static toy weights');
  const real = norm(await page.locator('#gpt2').innerText());
  for (const { text } of recorded.tokens) assert.ok(real.includes(text.trim()), 'recorded sentence remains readable');
  assert.match(await page.locator('body').innerText(), /JavaScript|static|snapshot/i, 'explain the static fallback');
  for (const note of await page.locator('[data-attn-note]').all()) assert.equal(await note.isVisible(), true);
  assert.equal(await page.locator('[data-attn-note]').count(), 2);
  const dimensions = await page.evaluate(() => ({ w: document.documentElement.scrollWidth, v: innerWidth }));
  assert.ok(dimensions.w <= dimensions.v + 1, 'readable fallback without document overflow');
});
