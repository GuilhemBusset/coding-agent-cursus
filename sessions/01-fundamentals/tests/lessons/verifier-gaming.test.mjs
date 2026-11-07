import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import vm from 'node:vm';
import { chromium } from '../../../../tools/html-pages/browser.mjs';
import { repoRoot, count, eventually, textOf } from '../../../../tools/html-pages/tests/component-helpers.mjs';

/* The verifier-gaming lab: a seeded hill climb that games a tolerant overlap scorer, four LP
 * "optimal" claims with duality certificates, and three agent patches to a failing test. Only the
 * public DOM contract is read; every displayed number is recomputed here. check-page.mjs supplies
 * the generic accessibility/layout gate. */
const file = path.join(repoRoot, 'sessions/01-fundamentals/cursus/labs/verifier-gaming.html');
const numberPattern = '-?\\d+(?:\\.\\d+)?';
const normalize = s => s.normalize('NFKC').replace(/−/g, '-').replace(/≤/g, '<=').replace(/≥/g, '>=');
const compact = s => normalize(s).replace(/[\s·*]/g, '').toLowerCase();
const close = (actual, expected, message) => assert.ok(Math.abs(actual - expected) < 1e-6, `${message}: ${actual} != ${expected}`);

// One browser for the file, a fresh context per test.
let browser;
after(() => browser?.close());
async function pageFor(t) {
  browser ??= await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  t.after(async () => { await context.close(); assert.deepEqual(errors, [], 'no runtime errors or remote requests'); });
  await context.route(/^(https?|wss?):/i, route => { errors.push(`remote request: ${route.request().url()}`); return route.abort(); });
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(pathToFileURL(file).href);
  return page;
}

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

const signature = state => ({ geometry: geometry(state).rects, trace: state.trace.map(row => row.text) });

test('hill climbing games the tolerant scorer but not the exact checker; Step and Run take the same path; Reset and reload replay the seed', async t => {
  // A small tolerance keeps the search short; any positive one is exploited.
  const page = await pageFor(t), tolerance = 2;
  const initial = signature(await setting(page, tolerance, false));
  const gamed = await stepToEnd(page, tolerance, false);
  const tolerant = geometry(gamed);
  assert.ok(gamed.trace.length > 0);
  assert.ok(tolerant.overlap > 0 && tolerant.overlap <= tolerance, 'the search exploits the tolerance');
  assert.deepEqual(signature(await setting(page, tolerance, false)), initial, 'Reset restores the initial drawing and clears the trace');
  assert.deepEqual(signature(await runToEnd(page)), signature(gamed), 'Run accepts exactly the moves Step accepts');
  await setting(page, tolerance, true);
  const honest = geometry(await stepToEnd(page, tolerance, true));
  assert.equal(honest.overlap, 0, 'the exact checker never accepts an overlap');
  assert.ok(tolerant.score > honest.score, 'the gamed score beats the honest one for the same seed');
  await page.reload();
  assert.deepEqual(signature(await setting(page, tolerance, false)), initial, 'a fresh load starts from the same seeded state');
});

test('changing the tolerance or the checker restarts the seeded search, even after it converged', async t => {
  const page = await pageFor(t);
  const initial = geometry(await setting(page, 7, false)).rects;
  // Converge by clicking Step in-page (the stepped and run paths are checked above).
  await page.locator('[data-gaming-step]').evaluate(button => { for (let n = 0; !button.disabled && n < 1000; n++) button.click(); });
  const exploit = await packingState(page);
  assert.ok(converged(exploit) && geometry(exploit).overlap > 0, 'the exploit first');
  const restarted = async message => {
    const state = await packingState(page);
    assert.deepEqual(geometry(state).rects, initial, message);
    assert.equal(state.trace.length, 0, message);
    await page.locator('[data-gaming-step]').click();
    await eventually(async () => assert.equal((await packingState(page)).trace.length, 1), `${message}: the search moves again`);
  };
  await setTolerance(page, 13);
  await restarted('changing the tolerance restarts');
  await page.locator('[data-gaming-exact]').check();
  await restarted('ticking the exact checker restarts');
  await page.locator('[data-gaming-exact]').uncheck();
  await restarted('unticking the exact checker restarts');
});

// The answer key agrees with the independent classification, and the card locks, reveals and
// resets on this page (predict.test.mjs covers the component itself).
async function predictKey(root, expectedKinds, classifyLabel) {
  await count(root, 1);
  const questions = root.locator('fieldset[data-predict-question]');
  await count(questions, expectedKinds.length);
  const label = radio => radio.evaluate(el => [...el.labels].map(l => l.textContent.trim()).join(' '));
  for (let i = 0; i < expectedKinds.length; i++) {
    const correct = questions.nth(i).locator('input[type=radio][data-correct]');
    await count(correct, 1);
    assert.equal(classifyLabel(await label(correct)), expectedKinds[i], 'answer key agrees with the independent oracle');
    await correct.check();
  }
  await root.locator('[data-predict-lock]').click();
  await root.locator('[data-predict-reveal]').click();
  for (let i = 0; i < expectedKinds.length; i++) {
    assert.equal(await textOf(questions.nth(i).locator('[data-predict-result]')), 'Correct.');
    assert.equal(await questions.nth(i).locator('[data-predict-answer]').isVisible(), true);
  }
  await root.locator('[data-predict-reset]').click();
  await count(root.locator('input:checked'), 0);
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

test('LP panel: displayed witnesses, objectives, bounds and duality gaps are correct, and so is the certification key', async t => {
  const page = await pageFor(t);
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
  await predictKey(panel.locator('[data-predict]'), answers, label => {
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

test('patch panel: each displayed patch passes its displayed suite, only the honest fix satisfies sum, and so is the key', async t => {
  const page = await pageFor(t);
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
  await predictKey(panel.locator('[data-predict]'), kinds, label => {
    if (/honest|real fix|correct fix/i.test(label)) return 'honest';
    if (/hard[ -]?cod/i.test(label)) return 'hard-code';
    assert.match(label, /test/i);
    return 'test-edit';
  });
});
