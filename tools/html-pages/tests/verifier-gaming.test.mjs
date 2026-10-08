import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import vm from 'node:vm';
import { chromium } from '../browser.mjs';
import { openPage, repoRoot, read, suites, count, enabled, eventually, textOf } from './component-helpers.mjs';

// Issue 36's agreed public DOM contract. No page functions or hidden simulation
// state are consulted. Citation accuracy and screenshot review are separate PR
// evidence; check-page.mjs supplies the generic accessibility/layout gate.
const file = path.join(repoRoot, 'sessions/01-fundamentals/cursus/labs/verifier-gaming.html');
const numberPattern = '-?\\d+(?:\\.\\d+)?';
const normalize = s => s.normalize('NFKC').replace(/−/g, '-').replace(/≤/g, '<=').replace(/≥/g, '>=');
const compact = s => normalize(s).replace(/[\s·*]/g, '').toLowerCase();
const close = (actual, expected, message) => assert.ok(Math.abs(actual - expected) < 1e-6, `${message}: ${actual} != ${expected}`);

async function visibleText(locator) {
  await count(locator, 1);
  assert.equal(await locator.isVisible(), true, 'required teaching content is visible');
  return locator.innerText();
}

function displayedNumber(text, expected, message, percent = false) {
  const match = normalize(text).match(new RegExp(`(${numberPattern})${percent ? '\\s*%' : ''}`));
  assert.ok(match, `${message}: no ${percent ? 'percentage' : 'number'} in ${text}`);
  const decimals = match[1].split('.')[1]?.length ?? 0;
  const rounding = 0.5 * 10 ** -decimals + 1e-8;
  assert.ok(Math.abs(Number(match[1]) - expected) <= rounding, `${message}: displayed ${match[1]}, independently calculated ${expected}`);
}

test('D1: session lab has the three panels, offline scripts and CI registration', async t => {
  const page = await openPage(t, chromium, { file });
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'lab');
  assert.equal(await page.locator('html').getAttribute('data-design-system'), 'cursus');
  assert.deepEqual(await page.locator('section[data-panel]').evaluateAll(els => els.map(el => el.id)),
    ['packing', 'lp-certificate', 'catch-the-agent']);
  await count(page.locator('[data-panel]'), 3);
  const reserved = await page.locator('*').evaluateAll(els => els.flatMap(el => [...el.attributes]
    .map(a => a.name).filter(n => n === 'data-lab' || n === 'data-reset' || n.startsWith('data-budget'))));
  assert.deepEqual(reserved, [], 'remove every starter budget marker');
  await count(page.locator('script[src], script[type="module"]'), 0);
  assert.ok(suites.includes('verifier-gaming'), 'register in component-helpers.mjs, not just npm');
  const pkg = JSON.parse(await read('setup/package.json'));
  assert.ok(pkg.scripts.test.split(/\s+/).includes('../tools/html-pages/tests/verifier-gaming.test.mjs'), 'register in the explicit npm suite list');
});

async function packingState(page) {
  return page.locator('#packing').evaluate(root => {
    const get = selector => {
      const el = root.querySelector(selector);
      if (!el || !el.checkVisibility()) throw new Error(`Missing/hidden readout ${selector}`);
      return el.innerText;
    };
    const rects = [...root.querySelectorAll('rect[data-square]')].map(rect => {
      let svg = rect.ownerSVGElement;
      while (svg.ownerSVGElement) svg = svg.ownerSVGElement;
      // Undo only the root SVG's viewport transform; retain group/rect transforms.
      const matrix = svg.getCTM().inverse().multiply(rect.getCTM());
      const x = rect.x.baseVal.value, y = rect.y.baseVal.value;
      const w = rect.width.baseVal.value, h = rect.height.baseVal.value;
      const points = [[x, y], [x + w, y], [x, y + h], [x + w, y + h]]
        .map(([px, py]) => new DOMPoint(px, py).matrixTransform(matrix));
      const box = rect.getBoundingClientRect();
      return {
        points: points.map(p => [p.x, p.y]),
        visible: rect.checkVisibility() && box.width > 0 && box.height > 0 &&
          getComputedStyle(rect).visibility !== 'hidden' && Number(getComputedStyle(rect).opacity) > 0,
        data: { ...rect.dataset },
      };
    });
    const trace = root.querySelector('[data-gaming-trace]');
    if (!trace || trace.tagName !== 'OL' || !trace.checkVisibility()) throw new Error('Trace must be a visible ordered list');
    return { rects, scoreText: get('[data-gaming-score]'), overlapText: get('[data-gaming-overlap]'),
      verdict: get('[data-gaming-verdict]'), status: get('[data-gaming-status]'),
      trace: [...trace.children].map(el => ({ tag: el.tagName, text: el.innerText, visible: el.checkVisibility() })) };
  });
}

function geometry(state) {
  assert.equal(state.rects.length, 4, 'draw exactly four squares');
  const rects = state.rects.map(({ points, visible, data }) => {
    assert.ok(visible, 'packing is rendered, not hidden metadata');
    points.flat().forEach(v => close(v, Math.round(v), 'integer-grid rendered coordinate'));
    const [[x, y], [right, top], [left, bottom], [lastX, lastY]] = points.map(p => p.map(Math.round));
    assert.deepEqual([top, left, lastX, lastY], [y, x, right, bottom], 'axis-aligned squares');
    assert.equal(right - x, 100, 'rendered side length');
    assert.equal(bottom - y, 100, 'rendered side length');
    for (const [key, value] of Object.entries(data)) {
      const dimension = key.replace(/^(?:square|rendered)/, '').toLowerCase();
      if (['x', 'y', 'width', 'height', 'left', 'right'].includes(dimension)) {
        close(Number(value), { x, y, width: 100, height: 100, left: x, right }[dimension], `data-${key} agrees with the drawing`);
      }
    }
    return { x, y, width: right - x };
  });
  assert.ok(rects.every(r => r.y === rects[0].y), 'all squares share a row');
  assert.ok(rects.every((r, i) => i === 0 || r.x > rects[i - 1].x), 'squares are ordered left to right');
  const gaps = rects.slice(1).map((r, i) => r.x - rects[i].x - 100);
  const result = geometryForGaps(gaps);
  displayedNumber(state.scoreText, result.score, 'packing score', true);
  displayedNumber(state.overlapText, result.overlap, 'largest pairwise overlap');
  const negative = /\b(fail\w*|reject\w*|invalid|infeasible)\b|\bnot\s+(?:pass\w*|valid|feasible|accept\w*)/i;
  if (result.overlap > 0) assert.match(state.verdict, negative, 'text must expose the exact-check failure');
  else {
    assert.doesNotMatch(state.verdict, negative);
    assert.match(state.verdict, /pass|accept|valid|feasible|(?:no|zero) overlap/i, 'text must state exact-check success');
  }
  assert.match(state.status, /running|converged/i);
  return { ...result, rects };
}

function geometryForGaps(gaps) {
  const xs = [0];
  for (const gap of gaps) xs.push(xs.at(-1) + 100 + gap);
  let overlap = 0;
  for (let i = 0; i < 4; i++) for (let j = i + 1; j < 4; j++) {
    overlap = Math.max(overlap, Math.max(0, Math.min(xs[i] + 100, xs[j] + 100) - Math.max(xs[i], xs[j])));
  }
  const width = Math.max(...xs.map(x => x + 100)) - Math.min(...xs);
  return { gaps, overlap, score: 400 / width * 100 };
}

const converged = state => /converged/i.test(state.status) && !/not\s+converged/i.test(state.status);

function traceRow(row, step, changed, score) {
  assert.equal(row.tag, 'LI');
  assert.ok(row.visible, 'accepted steps are visible');
  displayedNumber(row.text, score, `step ${step} trace score`, true);
  const text = normalize(row.text);
  // Step numbers may be supplied by native OL markers. Gap names may be 1–3,
  // A–C, g1–g3, or left/middle/right; no particular prose template is required.
  const explicitStep = text.match(/\bstep\s*#?\s*(\d+)/i);
  if (explicitStep) assert.equal(Number(explicitStep[1]), step);
  const gap = text.match(/\b(?:gap\s*|g\s*)(?:#\s*)?([1-3abc])\b/i);
  const named = text.match(/\b(left|middle|right)\s+gap\b/i);
  assert.ok(gap || named, `trace row names the changed gap: ${text}`);
  const index = gap ? (/\d/.test(gap[1]) ? Number(gap[1]) - 1 : 'abc'.indexOf(gap[1].toLowerCase()))
    : ['left', 'middle', 'right'].indexOf(named[1].toLowerCase());
  assert.equal(index, changed, 'trace identifies the actual changed gap');
}

async function setting(page, tolerance, exact) {
  await setTolerance(page, tolerance);
  await page.locator('input[data-gaming-exact]').setChecked(exact);
  await page.locator('[data-gaming-reset]').click();
  const state = await packingState(page);
  const result = geometry(state);
  assert.ok(result.gaps.every(g => g > 0), 'seeded initial gaps are positive');
  assert.equal(state.trace.length, 0, 'reset clears accepted-step history');
  return state;
}

async function setTolerance(page, value) {
  const slider = page.locator('input[data-gaming-tolerance]');
  await slider.focus();
  await slider.press('Home');
  for (let i = 0; i < value; i++) await slider.press('ArrowRight');
  assert.equal(await slider.inputValue(), String(value));
}

async function stepToEnd(page, tolerance, exact) {
  let state = await packingState(page), previous = geometry(state);
  const allowed = exact ? 0 : tolerance;
  // Each improving +/-1 move reduces total width by one. This is a bound from
  // the displayed initial geometry, not a chosen seed or an expected trace.
  const limit = previous.gaps.reduce((a, b) => a + b, 0) + 3 * allowed + 2;
  assert.ok(Number.isSafeInteger(limit) && limit > 0, 'finite integer search bound');
  let steps = 0;
  while (!converged(state)) {
    assert.ok(steps++ < limit, 'hill climb must terminate when no improving neighbour exists');
    const before = state;
    await page.locator('[data-gaming-step]').click();
    await eventually(async () => {
      state = await packingState(page);
      assert.ok(state.trace.length !== before.trace.length || converged(state), 'step updates trace or reports convergence');
    });
    const current = geometry(state);
    assert.ok(current.overlap <= allowed, 'every visited state passes the active scorer');
    if (state.trace.length === before.trace.length) {
      assert.ok(converged(state));
      assert.deepEqual(current.rects, previous.rects, 'a rejected move cannot change the drawing');
    } else {
      assert.equal(state.trace.length, before.trace.length + 1, 'Step accepts at most one move');
      assert.deepEqual(state.trace.slice(0, -1), before.trace, 'trace is append-only');
      const changed = current.gaps.map((g, i) => g - previous.gaps[i]);
      assert.equal(changed.filter(d => d !== 0).length, 1, 'only one gap changes');
      const index = changed.findIndex(d => d !== 0);
      assert.equal(Math.abs(changed[index]), 1, 'move is a +/-1 neighbour');
      assert.ok(current.score > previous.score, 'accepted move strictly improves the real score');
      traceRow(state.trace.at(-1), state.trace.length, index, current.score);
    }
    previous = current;
  }
  for (let i = 0; i < 3; i++) for (const delta of [-1, 1]) {
    const gaps = [...previous.gaps];
    gaps[i] += delta;
    const neighbour = geometryForGaps(gaps);
    assert.ok(neighbour.overlap > allowed || neighbour.score <= previous.score,
      'converged means no accepted, improving +/-1 neighbour');
  }
  return state;
}

async function runToEnd(page) {
  await page.locator('[data-gaming-run]').click();
  await page.waitForFunction(() => {
    const text = document.querySelector('#packing [data-gaming-status]')?.textContent ?? '';
    return /converged/i.test(text) && !/not\s+converged/i.test(text);
  }, undefined, { timeout: 30000 });
  const state = await packingState(page);
  geometry(state);
  return state;
}

test('D2: hill climbing exploits tolerance and exact checking rejects overlaps at every step', { timeout: 180000 }, async t => {
  const page = await openPage(t, chromium, { file });
  const range = page.locator('input[data-gaming-tolerance]');
  for (const [attr, value] of [['type', 'range'], ['min', '0'], ['max', '20'], ['step', '1']]) {
    assert.equal(await range.getAttribute(attr), value);
  }
  const exact = page.locator('input[data-gaming-exact]');
  assert.equal(await exact.getAttribute('type'), 'checkbox');
  for (const input of [range, exact]) {
    assert.ok(await input.evaluate(el => [...el.labels].some(label => label.innerText.trim())), 'native controls have visible labels');
  }
  assert.match(await exact.evaluate(el => [...el.labels].map(l => l.innerText).join(' ')), /exact checker/i);
  for (const action of ['step', 'run', 'reset']) await count(page.locator(`button[data-gaming-${action}]`), 1);
  for (const tolerance of [0, 7, 20]) {
    const results = [];
    for (const exactMode of [false, true]) {
      await setting(page, tolerance, exactMode);
      const state = await stepToEnd(page, tolerance, exactMode);
      const result = geometry(state);
      assert.ok(state.trace.length > 0);
      if (exactMode || tolerance === 0) assert.equal(result.overlap, 0);
      else assert.ok(result.overlap > 0 && result.overlap <= tolerance);
      results.push(result);
    }
    if (tolerance > 0) assert.ok(results[0].score > results[1].score, 'tolerant score beats the exact result for the same seed');
  }
});

test('D2: changing either setting after an exploit restarts the seeded search', async t => {
  const page = await openPage(t, chromium, { file });
  const initial = await setting(page, 7, false);
  assert.ok(geometry(await runToEnd(page)).overlap > 0);
  await setTolerance(page, 13);
  let state = await packingState(page);
  assert.deepEqual(geometry(state).rects, geometry(initial).rects);
  assert.equal(state.trace.length, 0);
  assert.ok(geometry(await runToEnd(page)).overlap > 0);
  await page.locator('[data-gaming-exact]').check();
  state = await packingState(page);
  assert.deepEqual(geometry(state).rects, geometry(initial).rects);
  assert.equal(state.trace.length, 0);
  assert.equal(geometry(await runToEnd(page)).overlap, 0);
  await page.locator('[data-gaming-exact]').uncheck();
  state = await packingState(page);
  assert.deepEqual(geometry(state).rects, geometry(initial).rects);
  assert.equal(state.trace.length, 0);
});

async function exercisePredict(root, expectedKinds, classifyLabel) {
  await count(root, 1);
  const questions = root.locator('fieldset[data-predict-question]');
  await count(questions, expectedKinds.length);
  const label = radio => radio.evaluate(el => [...el.labels].map(l => l.textContent.trim()).join(' '));
  const resetState = async () => {
    await enabled(root.locator('[data-predict-lock]'), false);
    await enabled(root.locator('[data-predict-reveal]'), false);
    await count(root.locator('input:checked'), 0);
    for (const q of await questions.all()) {
      for (const radio of await q.locator('input[type=radio]').all()) await enabled(radio);
      assert.equal(await q.locator('[data-predict-answer]').isVisible(), false);
      assert.equal(await textOf(q.locator('[data-predict-result]')), '');
    }
  };
  for (let i = 0; i < expectedKinds.length; i++) {
    const q = questions.nth(i);
    await count(q.locator('input[type=radio][data-correct]'), 1);
    assert.equal(classifyLabel(await label(q.locator('input[data-correct]'))), expectedKinds[i], 'answer key agrees with independent oracle');
    assert.ok((await textOf(q.locator('legend'))).length > 0);
    const labels = [];
    for (const radio of await q.locator('input[type=radio]').all()) labels.push(classifyLabel(await label(radio)));
    assert.deepEqual([...new Set(labels)].sort(), [...new Set(expectedKinds)].sort(), 'all classification choices are offered');
  }
  await resetState();
  for (const mode of ['wrong', 'mixed', 'correct']) {
    const selectedCorrect = [];
    for (let i = 0; i < expectedKinds.length; i++) {
      const correct = mode === 'correct' || (mode === 'mixed' && i % 2 === 0);
      selectedCorrect.push(correct);
      await questions.nth(i).locator(`input[type=radio]${correct ? '[data-correct]' : ':not([data-correct])'}`).first().check();
      if (i < expectedKinds.length - 1) await enabled(root.locator('[data-predict-lock]'), false);
    }
    await enabled(root.locator('[data-predict-reveal]'), false);
    await root.locator('[data-predict-lock]').click();
    for (const radio of await root.locator('input[type=radio]').all()) await enabled(radio, false);
    for (const answer of await root.locator('[data-predict-answer]').all()) assert.equal(await answer.isVisible(), false);
    await root.locator('[data-predict-reveal]').click();
    for (let i = 0; i < expectedKinds.length; i++) {
      const q = questions.nth(i);
      assert.equal(await q.locator('[data-predict-answer]').isVisible(), true);
      assert.ok((await textOf(q.locator('[data-predict-answer]'))).length > 10, 'revealed answer explains why');
      assert.equal(await textOf(q.locator('[data-predict-result]')), selectedCorrect[i] ? 'Correct.'
        : `Not quite. The answer is ${await label(q.locator('input[data-correct]'))}.`);
    }
    await root.locator('[data-predict-reset]').click();
    await resetState();
  }
}

function witness(text, names) {
  text = normalize(text);
  const values = names.map(name => text.match(new RegExp(`\\b${name}\\s*=\\s*(${numberPattern})`, 'i')));
  if (values.every(Boolean)) return values.map(m => Number(m[1]));
  const tuples = [...text.matchAll(/\(([^()]*)\)/g)].map(m => m[1].trim().split(/\s*,\s*/));
  const tuple = tuples.find(parts => parts.length === names.length && parts.every(s => new RegExp(`^${numberPattern}$`).test(s)));
  assert.ok(tuple, `visible ${names.join(',')} witness needs named values or a numeric tuple: ${text}`);
  return tuple.map(Number);
}

function labelledValue(text, labels, expected) {
  const re = new RegExp(`(?:${labels})\\s*(?:\\([^)]*\\))?\\s*[:=]?\\s*(${numberPattern})`, 'i');
  const match = normalize(text).match(re);
  assert.ok(match, `missing displayed ${labels}: ${text}`);
  close(Number(match[1]), expected, `displayed ${labels}`);
}

function feasibilityText(text, side, expected) {
  const match = text.match(new RegExp(`\\b${side}\\s+(?:feasible|feasibility)\\s*[:=?–—-]?\\s*(not feasible|infeasible|feasible|yes|no|true|false)\\b`, 'i'))
    ?? text.match(new RegExp(`\\b${side}\\s*[:=–—-]?\\s*(not feasible|infeasible|feasible|yes|no)\\b`, 'i'));
  assert.ok(match, `show ${side} feasibility explicitly`);
  assert.equal(/^(feasible|yes|true)$/i.test(match[1]), expected, `${side} feasibility agrees with constraints`);
}

test('D3: visible witnesses, real duality gaps and student certification decisions agree', async t => {
  const page = await openPage(t, chromium, { file });
  const panel = page.locator('#lp-certificate');
  const model = compact(await visibleText(panel.locator('[data-lp-model]')));
  assert.match(model, /(?<![\d.])3x\+2y(?![\d.])/);
  assert.match(model, /(?<![\d.])4u\+2v\+3w(?![\d.])/);
  assert.match(model, /max(?:imi[sz]e)?[^<>]*?3x\+2y/);
  assert.match(model, /min(?:imi[sz]e)?[^<>]*?4u\+2v\+3w/);
  const constraints = [...model.matchAll(/((?:\d+(?:\.\d+)?)?[xyuvw](?:[+,](?:\d+(?:\.\d+)?)?[xyuvw])*)(<=|>=)(-?\d+(?:\.\d+)?)/g)]
    .flatMap(([, lhs, relation, rhs]) => lhs.split(',').map(term => `${term}${relation}${rhs}`));
  assert.deepEqual([...new Set(constraints)].sort(),
    ['x+y<=4', 'x<=2', 'y<=3', 'x>=0', 'y>=0', 'u+v>=3', 'u+w>=2', 'u>=0', 'v>=0', 'w>=0'].sort(),
    'visible coefficients and constraints equal the independent LP, including nonnegativity');
  const claims = panel.locator('[data-lp-claim]');
  await count(claims, 4);
  const expectedWitnesses = [ [[1, 3], [2, 1, 0]], [[2, 2], [2, 1, 0]], [[3, 0.5], null], [[2, 2], [1, 3, 0]] ];
  const answers = [];
  for (let i = 0; i < 4; i++) {
    const card = claims.nth(i);
    const text = await visibleText(card);
    assert.match(text, /\boptimal\b/i, 'each agent claims optimal');
    const primal = witness(await visibleText(card.locator('[data-lp-primal]')), ['x', 'y']);
    const dual = witness(await visibleText(card.locator('[data-lp-dual]')), ['u', 'v', 'w']);
    assert.deepEqual(primal, expectedWitnesses[i][0]);
    if (expectedWitnesses[i][1]) assert.deepEqual(dual, expectedWitnesses[i][1]);
    const [x, y] = primal, [u, v, w] = dual;
    const primalFeasible = x >= 0 && y >= 0 && x + y <= 4 && x <= 2 && y <= 3;
    const dualFeasible = u >= 0 && v >= 0 && w >= 0 && u + v >= 3 && u + w >= 2;
    const objective = 3 * x + 2 * y, bound = 4 * u + 2 * v + 3 * w;
    feasibilityText(text, 'primal', primalFeasible);
    feasibilityText(text, 'dual', dualFeasible);
    labelledValue(text, '(?:primal\\s+)?objective|\\bz', objective);
    labelledValue(text, '(?:dual\\s+)?bound|dual\\s+objective', bound);
    const certified = primalFeasible && dualFeasible && bound === objective;
    answers.push(certified ? 'certified' : 'not-certified');
    const gauge = card.locator('[data-lp-gauge-state]');
    // The marker may be on the card itself or a gauge container inside it.
    const state = await card.getAttribute('data-lp-gauge-state') ?? await gauge.getAttribute('data-lp-gauge-state');
    const meter = card.locator('meter[data-lp-gap]');
    if (primalFeasible && dualFeasible) {
      assert.equal(state, 'gap');
      await count(meter, 1);
      assert.ok(await meter.isVisible());
      assert.notEqual(await meter.getAttribute('value'), null, 'feasible witnesses supply an explicit meter value');
      close(Number(await meter.getAttribute('value')), bound - objective, 'meter carries the true gap');
      close(await meter.evaluate(el => el.value), bound - objective, 'native meter must not clamp the gap');
      labelledValue(text, '(?:duality\\s+)?gap', bound - objective);
    } else {
      assert.equal(state, 'unavailable');
      assert.match(text, /certificate unavailable/i);
      // A hidden meter with a stale numeric value is also misleading evidence.
      await count(card.locator('meter[data-lp-gap][value]'), 0);
      for (const m of await meter.all()) assert.equal(await m.isVisible(), false);
      const math = compact(text);
      if (x > 2) assert.ok(math.includes('x<=2'), 'name violated primal constraint');
      if (u + w < 2) assert.ok(math.includes('u+w>=2'), 'name violated dual constraint');
    }
  }
  assert.deepEqual(answers, ['not-certified', 'certified', 'not-certified', 'not-certified']);
  await exercisePredict(panel.locator('[data-predict]'), answers, label => {
    if (/not certified/i.test(label)) return 'not-certified';
    assert.match(label, /certified optimal/i);
    return 'certified';
  });
});

// A deliberately small unified-diff reader, with exact context and hunk-count
// checks. It never shells out, writes snippets to disk, or executes page code.
function applyDiff(base, diff) {
  const files = { ...base }, changed = new Set(), additions = [];
  const lines = diff.replace(/\r\n/g, '\n').replace(/\n$/, '').split('\n');
  const pathname = line => line.slice(4).split(/\t/)[0].replace(/^[ab]\//, '');
  let i = 0;
  while (i < lines.length) {
    if (/^(diff --git |index )/.test(lines[i]) || lines[i] === '') { i++; continue; }
    assert.ok(lines[i].startsWith('--- '), `expected unified diff header: ${lines[i]}`);
    const oldPath = pathname(lines[i++]);
    assert.ok(lines[i]?.startsWith('+++ '));
    const newPath = pathname(lines[i++]);
    assert.equal(newPath, oldPath, 'examples modify existing files, without renaming');
    assert.ok(Object.hasOwn(base, oldPath), `diff references displayed base ${oldPath}`);
    assert.ok(!changed.has(oldPath), 'one diff section per file');
    changed.add(oldPath);
    const original = base[oldPath].replace(/\r\n/g, '\n').replace(/\n$/, '').split('\n');
    const out = [];
    let cursor = 0, hunks = 0;
    while (i < lines.length && lines[i].startsWith('@@')) {
      const h = lines[i++].match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
      assert.ok(h, 'valid hunk header');
      hunks++;
      const start = Number(h[1]) - 1, oldCount = Number(h[2] ?? 1), newCount = Number(h[4] ?? 1);
      assert.ok(start >= cursor && start <= original.length, 'hunks are ordered and in bounds');
      out.push(...original.slice(cursor, start));
      cursor = start;
      assert.equal(out.length, Number(h[3]) - 1, 'new hunk position matches preceding changes');
      let consumed = 0, produced = 0;
      while (i < lines.length && !/^(?:@@|--- |diff --git )/.test(lines[i])) {
        const line = lines[i];
        if (line === '\\ No newline at end of file') { i++; continue; }
        if (consumed === oldCount && produced === newCount) break;
        i++;
        assert.ok([' ', '-', '+'].includes(line[0]), `invalid diff line: ${line}`);
        if (line[0] !== '+') {
          assert.equal(original[cursor++], line.slice(1), 'diff context/deletion matches displayed base exactly');
          consumed++;
        }
        if (line[0] !== '-') { out.push(line.slice(1)); produced++; }
        if (line[0] === '+') additions.push({ file: oldPath, text: line.slice(1) });
      }
      assert.equal(consumed, oldCount, 'old hunk line count');
      assert.equal(produced, newCount, 'new hunk line count');
    }
    assert.ok(hunks > 0, 'each file change contains a hunk');
    out.push(...original.slice(cursor));
    files[oldPath] = out.join('\n');
  }
  assert.ok(changed.size > 0, 'diff changes at least one file');
  return { files, changed: [...changed], additions };
}

function sandbox(files) {
  // Supports tiny plain scripts and conventional CommonJS or named ESM snippets.
  // Module syntax is adapted only for these two displayed files, not arbitrary
  // imports; no filesystem, process, or host require is exposed to the snippets.
  const implementation = files['sum.js'].replace(/\bexport\s+(?=(?:function|const|let|var)\b)/g, '');
  const context = vm.createContext({}, { codeGeneration: { strings: false, wasm: false } });
  vm.runInContext(`
    const module = { exports: {} }; const exports = module.exports;
    let __assertionCount = 0;
    const assert = Object.assign(function assert(value, message) {
      __assertionCount++;
      if (!value) throw Error(message || 'assertion failed');
    }, { equal(a,b) { __assertionCount++; if (a != b) throw Error('not equal'); },
         strictEqual(a,b) { __assertionCount++; if (a !== b) throw Error('not strictly equal'); } });
    assert.ok = assert;
    const console = { assert };
    ${implementation}
    const __testedSum = typeof sum === 'function' ? sum :
      (typeof module.exports === 'function' ? module.exports : module.exports.sum);
    if (typeof __testedSum !== 'function') throw Error('sum.js must define sum');
  `, context, { timeout: 250 });
  return context;
}

function runDisplayedSuite(files) {
  const context = sandbox(files);
  // These imports bind the same sum/assert already available in the isolated VM.
  const suite = files['sum.test.js']
    .replace(/^\s*import\s+[^;\n]+\s+from\s+['"](?:\.\/sum\.js|node:assert(?:\/strict)?|assert(?:\/strict)?)['"];?\s*$/gm, '')
    .replace(/^\s*(?:const|let|var)\s+[^;\n]+?=\s*require\(['"](?:\.\/sum(?:\.js)?|node:assert(?:\/strict)?|assert(?:\/strict)?)['"]\);?\s*$/gm, '');
  vm.runInContext(suite, context, { timeout: 250 });
  assert.ok(vm.runInContext('__assertionCount > 0', context, { timeout: 250 }), 'displayed suite executes an assertion');
}

function meetsSumContract(files) {
  const context = sandbox(files);
  const inputs = [[], [7], [2, 3], [-4, 1], [1, 2, 3, 4, 5], [0, 0], [2.5, -0.5, 8],
    ...Array.from({ length: 12 }, (_, n) => Array.from({ length: n + 1 }, (_, k) => ((n * 7 + k * 11) % 23) - 11))];
  return inputs.every(values => {
    const expected = values.reduce((total, value) => total + value, 0);
    try {
      const result = vm.runInContext(`__testedSum(${JSON.stringify(values)})`, context, { timeout: 250 });
      return typeof result === 'number' && result === expected;
    } catch { return false; }
  });
}

test('D4: displayed patches pass their suites but only the honest fix satisfies sum', async t => {
  const page = await openPage(t, chromium, { file });
  const panel = page.locator('#catch-the-agent');
  const base = {};
  await count(panel.locator('pre[data-diff-base]'), 2);
  for (const pre of await panel.locator('pre[data-diff-base]').all()) base[await pre.getAttribute('data-diff-base')] = await visibleText(pre);
  assert.deepEqual(Object.keys(base).sort(), ['sum.js', 'sum.test.js']);
  assert.match(base['sum.js'], /return\s+values\.length\b/);
  assert.match(base['sum.test.js'], /sum\s*\(\s*\[\s*2\s*,\s*3\s*\]\s*\)\s*(?:===|==|,)\s*5\b/);
  assert.throws(() => runDisplayedSuite(base), 'the displayed test must fail on the broken base');
  assert.equal(meetsSumContract(base), false);
  const diffs = panel.locator('pre[data-diff]');
  await count(diffs, 3);
  const kinds = [];
  for (const pre of await diffs.all()) {
    const patch = applyDiff(base, await visibleText(pre));
    assert.doesNotThrow(() => runDisplayedSuite(patch.files), 'each patched version passes its own displayed suite');
    const honest = meetsSumContract(patch.files);
    let kind;
    if (patch.changed.length === 1 && patch.changed[0] === 'sum.test.js') {
      kind = 'test-edit';
      assert.equal(honest, false);
      assert.ok(patch.additions.some(a => /sum\s*\(\s*\[\s*2\s*,\s*3\s*\]\s*\)\s*(?:===|==|,)\s*2\b/.test(a.text)),
        'test edit changes the expected result to 2 for the same input');
    } else {
      assert.deepEqual(patch.changed, ['sum.js'], 'implementation patches do not modify tests');
      kind = honest ? 'honest' : 'hard-code';
      if (!honest) assert.ok(patch.additions.some(a => /\breturn\s+5\b/.test(a.text)), 'hard-code returns the expected literal');
    }
    kinds.push(kind);
  }
  assert.deepEqual([...kinds].sort(), ['hard-code', 'honest', 'test-edit']);
  assert.notEqual(kinds.at(-1), 'honest', 'honest fix is not always the last choice');
  const tells = panel.locator('details').filter({ hasText: /git diff --stat/ });
  await count(tells, 1);
  assert.equal(await tells.getAttribute('open'), null, 'tells start concealed');
  await tells.locator('summary').click();
  assert.match(await visibleText(tells), /sum\.test\.js|test files|tests\//i);
  await tells.locator('summary').click();
  await exercisePredict(panel.locator('[data-predict]'), kinds, label => {
    if (/honest|real fix|correct fix/i.test(label)) return 'honest';
    if (/hard[ -]?cod/i.test(label)) return 'hard-code';
    assert.match(label, /test/i);
    return 'test-edit';
  });
});

test('A1: reset, fresh loads, Step and Run reproduce the same seed, trace and drawing', { timeout: 120000 }, async t => {
  const page = await openPage(t, chromium, { file });
  const seed = await page.locator('#packing').getAttribute('data-seed');
  assert.match(seed ?? '', /^\d+$/, 'display a fixed integer seed');
  assert.ok((await visibleText(page.locator('#packing'))).includes(seed), 'seed is visible to students');
  const signature = state => ({ geometry: geometry(state).rects, trace: state.trace.map(row => row.text) });
  for (const exact of [false, true]) {
    const initial = signature(await setting(page, 11, exact));
    const stepped = signature(await stepToEnd(page, 11, exact));
    assert.deepEqual(signature(await setting(page, 11, exact)), initial, 'Reset restores the initial drawing and trace');
    assert.deepEqual(signature(await runToEnd(page)), stepped, 'Run and Step have identical accepted traces and geometry');
    for (let load = 0; load < 2; load++) {
      await page.reload();
      assert.equal(await page.locator('#packing').getAttribute('data-seed'), seed);
      assert.deepEqual(signature(await setting(page, 11, exact)), initial, 'fresh load preserves initial state');
      assert.deepEqual(signature(await runToEnd(page)), stepped, 'fresh load preserves the search trace');
    }
  }
});

test('A1: each invented panel is labelled and the cited case and reference dates are separate', async t => {
  const page = await openPage(t, chromium, { file });
  for (const panel of await page.locator('[data-panel]').all()) {
    const callout = panel.locator('.callout[data-illustrative]');
    assert.match(await visibleText(callout), /illustrative/i);
    assert.ok(await callout.evaluate(el => {
      const panel = el.closest('[data-panel]');
      const interactive = panel.querySelector('input, button, svg, pre, [data-lp-model], [data-lp-claim]');
      return !interactive || !!(el.compareDocumentPosition(interactive) & Node.DOCUMENT_POSITION_FOLLOWING);
    }), 'illustrative notice introduces the example before its controls/data');
  }
  const cited = page.locator('[data-cited]');
  const citationText = await visibleText(cited);
  assert.equal(await cited.evaluate(el => el.closest('[data-panel]') !== null), false);
  await count(cited.locator('a[href="https://arxiv.org/abs/2511.02864"]'), 1);
  assert.match(citationText, /2025-12-22/);
  const wei = page.locator('a[href="https://www.jasonwei.net/blog/asymmetry-of-verification-and-verifiers-law"]');
  assert.ok(await wei.count() >= 1);
  assert.ok(await wei.first().isVisible());
  assert.match(await page.locator('body').innerText(), /2025-07-15/);
  // Prose (all inventions identified, restarting explained, cited-case accuracy,
  // attribution to Wei, and the three tells) is reviewed under ADR 0011 §6.
});
