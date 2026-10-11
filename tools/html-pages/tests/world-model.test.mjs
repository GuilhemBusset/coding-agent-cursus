import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { chromium } from '../browser.mjs';
import { repoRoot, suites, openPage, eventually } from './component-helpers.mjs';

/* Issue 32: numerical interchange conventions for the agreed WorldModel API.
 * These fill gaps in the design's return shapes, not application-private hooks.
 * Arrays or typed arrays may be used. States/actions are [x,y,vx,vy]/[ux,uy].
 * fitDynamics takes [{state, action, nextState}], returning {A(4x4),B(4x2),c(4)}.
 * cemPlan(model,state,opts) takes {seed,rng,N,K,I,H,initialMean?,initialStd?}.
 * A plan exposes {state,actions,predictedPath,iterations}; iterations expose
 * {sequences,costs,eliteIndices,meanBefore,stdBefore,meanAfter,stdAfter}.
 * std is the population elite std, floored by config.planner.minStd (default 0),
 * with optional documented smoothing alpha (default 1): new=(1-alpha)*old+alpha*fit.
 * Final actions are the final mean, unless selectedIndex names a sampled sequence.
 * Cost = goalWeight*terminal Euclidean distance + obstacleWeight*(number of
 * segment-circle intersections) + effortWeight*sum(u²). Weights, action bound,
 * start/goal/obstacle are exposed in config (root or config.planner/world).
 * Aliases below allow conventional alternate field spellings; no private DOM ids.
 * run{Open,Closed}Loop(seed,error) returns records or {records,plans}; each executed
 * step records {state,action,nextState,planId,plan}. Plans may instead live in plans.
 * A predictedPath includes the plan's starting position, followed by H predictions.
 * Open's plan stays fixed; closed's successive initial means shift the last mean,
 * with an unconstrained final action. A record is an executed step, not a t=0 stub.
 * config.orbit exposes {dt,G,centralMass,centralPosition,addedPosition,softening,
 * initialStates:[state,state],times:[...],trainEnd,harmonics}. Times are multiples
 * of dt, include held-out samples, and are shared by both particles.
 * simulateOrbits(mass) returns two {times,points} series (or {orbits:[...]});
 * fitOrbit([{t,x,y},...]) returns {period,coefficients:[xCoeffs,yCoeffs]} where
 * coefficient order is [constant,cos(1),sin(1),...,cos(h),sin(h)].
 * predictOrbit(fit,times) returns points (or {points}). Period and harmonic count
 * remain chosen by the page; alternate-data tests prevent a baseline-only answer.
 * No review wording is prescribed. Prose/source accuracy is an agent review;
 * this suite only binds its evidence to the current HTML and checks structure.
 */
const relative = 'sessions/01-fundamentals/cursus/labs/world-model';
const file = path.join(repoRoot, `${relative}.html`);
const reviewFile = path.join(repoRoot, relative, 'review.md');
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const S = { error: '[data-wm-error]', seed: '[data-wm-seed]', mass: '[data-kepler-mass]',
  step: '[data-wm-step]', run: '[data-wm-run]', reset: '[data-wm-reset]', t: '[data-wm-t]' };
const pick = (o, ...keys) => keys.map(k => o?.[k]).find(v => v !== undefined);
const numbers = text => (text.match(/[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?/gi) || []).map(Number);
const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const point = p => Array.isArray(p) ? p.slice(0, 2) : [p.x, p.y];
const points = p => (pick(p, 'points', 'path', 'predictedPath') ?? p).map(point);
function near(a, b, tolerance = 1e-8, label = 'number') {
  assert.ok(Number.isFinite(a) && Number.isFinite(b), `${label}: finite (${a}, ${b})`);
  assert.ok(Math.abs(a - b) <= tolerance, `${label}: ${a} != ${b}, tolerance ${tolerance}`);
}
function vector(a, b, tolerance = 1e-8, label = 'vector') {
  assert.ok(Array.isArray(a) && Array.isArray(b), `${label}: arrays`);
  assert.equal(a.length, b.length, `${label}: length`);
  a.forEach((v, i) => Array.isArray(b[i]) ? vector(v, b[i], tolerance, `${label}[${i}]`) : near(v, b[i], tolerance, `${label}[${i}]`));
}
function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6D2B79F5) >>> 0;
    let v = Math.imul(s ^ (s >>> 15), s | 1);
    v ^= v + Math.imul(v ^ (v >>> 7), v | 61);
    return ((v ^ (v >>> 14)) >>> 0) / 4294967296;
  };
}
function affine(model, state, action) {
  return model.A.map((row, i) => row.reduce((v, a, j) => v + a * state[j], model.c[i]) +
    model.B[i].reduce((v, b, j) => v + b * action[j], 0));
}
// Pivoted elimination of normal equations, independent of the page's fitter.
function leastSquares(rows, values) {
  const n = rows[0].length;
  const aug = Array.from({ length: n }, (_, i) => [
    ...Array.from({ length: n }, (_, j) => rows.reduce((sum, row) => sum + row[i] * row[j], 0)),
    rows.reduce((sum, row, k) => sum + row[i] * values[k], 0),
  ]);
  for (let i = 0; i < n; i++) {
    let pivot = i;
    for (let k = i + 1; k < n; k++) if (Math.abs(aug[k][i]) > Math.abs(aug[pivot][i])) pivot = k;
    [aug[i], aug[pivot]] = [aug[pivot], aug[i]];
    assert.ok(Math.abs(aug[i][i]) > 1e-11, 'full-rank independent fit');
    const scale = aug[i][i];
    for (let j = i; j <= n; j++) aug[i][j] /= scale;
    for (let k = 0; k < n; k++) if (k !== i) {
      const multiple = aug[k][i];
      for (let j = i; j <= n; j++) aug[k][j] -= multiple * aug[i][j];
    }
  }
  return aug.map(row => row[n]);
}
function fitAffine(transitions) {
  const rows = transitions.map(r => [...r.state, ...r.action, 1]);
  const coeffs = Array.from({ length: 4 }, (_, i) => leastSquares(rows, transitions.map(r => r.nextState[i])));
  return { A: coeffs.map(r => r.slice(0, 4)), B: coeffs.map(r => r.slice(4, 6)), c: coeffs.map(r => r[6]) };
}
function modelNear(a, b, tolerance = 1e-8) {
  for (const key of ['A', 'B', 'c']) vector(a[key], b[key], tolerance, key);
}
function segmentHits(a, b, circle) {
  const dx = b[0] - a[0], dy = b[1] - a[1], d2 = dx * dx + dy * dy;
  const t = d2 === 0 ? 0 : Math.max(0, Math.min(1, ((circle.center[0] - a[0]) * dx + (circle.center[1] - a[1]) * dy) / d2));
  return distance([a[0] + t * dx, a[1] + t * dy], circle.center) <= circle.radius;
}
function circle(c) {
  assert.ok(c, 'expose circle geometry in config');
  return { center: pick(c, 'center', 'position') ?? [c.x, c.y], radius: pick(c, 'radius', 'r') };
}
function plannerConfig(c) {
  const p = { ...c, ...c.world, ...c.planner }, weights = p.cost ?? p.weights ?? {};
  const opts = {};
  for (const k of ['N', 'K', 'I', 'H']) {
    opts[k] = p[k];
    assert.ok(Number.isInteger(opts[k]) && opts[k] > 0, `positive planner ${k}`);
  }
  assert.ok(opts.K < opts.N && opts.I >= 2 && opts.H >= 2, 'CEM has multiple iterations and a proper elite subset');
  const actionLimit = pick(p, 'actionLimit', 'actionBound', 'maxAction', 'uMax');
  assert.ok(Number.isFinite(actionLimit) && actionLimit > 0, 'expose scalar bounded control limit');
  const weight = (key, alias) => pick(weights, key, alias) ?? pick(p, `${key}Weight`, `w${key[0].toUpperCase()}${key.slice(1)}`);
  const w = { goal: weight('goal', 'distance'), obstacle: weight('obstacle', 'collision'), effort: weight('effort', 'action') };
  for (const [key, value] of Object.entries(w)) assert.ok(Number.isFinite(value) && value > 0, `expose positive ${key} cost weight`);
  return { ...opts, actionLimit, weights: w, start: pick(p, 'start', 'initialState'),
    goal: circle(p.goal), obstacle: circle(p.obstacle), minStd: p.minStd ?? 0, alpha: p.alpha ?? 1 };
}
function rollout(model, state, actions) {
  const states = [state];
  for (const u of actions) states.push(affine(model, states.at(-1), u));
  return states;
}
function cost(model, state, actions, cfg) {
  const states = rollout(model, state, actions);
  const hits = states.slice(1).reduce((n, s, i) => n + Number(segmentHits(states[i], s, cfg.obstacle)), 0);
  const effort = actions.flat().reduce((n, u) => n + u * u, 0);
  return cfg.weights.goal * distance(states.at(-1), cfg.goal.center) + cfg.weights.obstacle * hits + cfg.weights.effort * effort;
}
function planView(p) {
  assert.ok(p, 'each computed plan must be inspectable');
  return { raw: p, state: pick(p, 'state', 'startState', 'observedState'), actions: pick(p, 'actions', 'sequence'),
    path: pick(p, 'predictedPath', 'predicted', 'path'), iterations: pick(p, 'iterations', 'diagnostics') };
}
function auditPlan(raw, model, state, cfg) {
  const p = planView(raw);
  vector(p.state, state, 1e-8, 'plan starts at observation');
  assert.equal(p.actions.length, cfg.H);
  assert.equal(p.iterations.length, cfg.I, 'all CEM diagnostics');
  let prior;
  for (const [index, d] of p.iterations.entries()) {
    const samples = pick(d, 'sequences', 'samples', 'sampledSequences');
    const elites = pick(d, 'eliteIndices', 'elites');
    const before = pick(d, 'meanBefore', 'mean'), beforeStd = pick(d, 'stdBefore', 'std');
    const after = pick(d, 'meanAfter', 'newMean'), afterStd = pick(d, 'stdAfter', 'newStd');
    assert.equal(samples.length, cfg.N, 'N sampled sequences');
    assert.equal(d.costs.length, cfg.N);
    vector(before, before, 0); vector(beforeStd, beforeStd, 0);
    assert.equal(before.length, cfg.H); assert.equal(beforeStd.length, cfg.H);
    if (prior) { vector(before, prior.mean, 1e-8, 'refitted mean used next'); vector(beforeStd, prior.std, 1e-8, 'refitted std used next'); }
    const expectedCosts = samples.map(sequence => {
      assert.equal(sequence.length, cfg.H);
      sequence.forEach(u => { assert.equal(u.length, 2); u.forEach(a => assert.ok(Number.isFinite(a) && Math.abs(a) <= cfg.actionLimit + 1e-10, 'sampled actions bounded')); });
      return cost(model, state, sequence, cfg);
    });
    vector(d.costs, expectedCosts, 1e-6, `iteration ${index} independently scored`);
    assert.equal(new Set(elites).size, cfg.K); assert.equal(elites.length, cfg.K);
    const sorted = expectedCosts.map((_, i) => i).sort((a, b) => expectedCosts[a] - expectedCosts[b] || a - b);
    assert.ok(elites.every(i => Number.isInteger(i) && i >= 0 && i < cfg.N));
    // Allow any tie ordering but no higher-cost sample in place of a lower-cost one.
    assert.ok(Math.max(...elites.map(i => expectedCosts[i])) <= expectedCosts[sorted[cfg.K - 1]] + 1e-7, 'K lowest costs retained');
    const means = Array.from({ length: cfg.H }, (_, h) => [0, 1].map(j => elites.reduce((s, i) => s + samples[i][h][j], 0) / cfg.K));
    const stds = means.map((m, h) => m.map((mu, j) => Math.max(cfg.minStd,
      Math.sqrt(elites.reduce((s, i) => s + (samples[i][h][j] - mu) ** 2, 0) / cfg.K))));
    const smooth = (fitted, previous) => fitted.map((r, h) => r.map((v, j) => cfg.alpha * v + (1 - cfg.alpha) * previous[h][j]));
    vector(after, smooth(means, before), 1e-7, 'elite mean update');
    vector(afterStd, smooth(stds, beforeStd), 1e-7, 'elite population std update');
    const distinct = new Set(samples.map(s => JSON.stringify(s)));
    assert.ok(distinct.size > cfg.K, 'genuine varied sampled search');
    prior = { mean: after, std: afterStd, samples };
  }
  const selected = pick(raw, 'selectedIndex', 'bestIndex');
  vector(p.actions, selected === undefined ? prior.mean : prior.samples[selected], 1e-8, 'executed sequence comes from CEM');
  vector(points(p.path), rollout(model, state, p.actions).map(point), 1e-7, 'predicted path rolled through learned model');
  return p;
}

async function pageFor(t, options = {}) {
  const page = await openPage(t, chromium, { file, offline: true, ...options });
  if (options.javaScriptEnabled !== false) {
    await page.waitForFunction(() => window.WorldModel && typeof WorldModel.cemPlan === 'function');
    await eventually(async () => assert.equal((await time(page)).k, 0), 'initial paused scene');
  }
  return page;
}
async function api(page, method, args = []) {
  return page.evaluate(({ method, args }) => {
    const result = method === 'config' ? WorldModel.config : WorldModel[method](...args);
    return JSON.parse(JSON.stringify(result, (_key, value) => ArrayBuffer.isView(value) ? Array.from(value) : value));
  }, { method, args });
}
async function limits(page, selector) {
  return page.locator(selector).evaluate(el => ({ min: +el.min, max: +el.max, step: el.step === 'any' ? 0 : +(el.step || 1), value: +el.value, default: +el.defaultValue }));
}
function rangeAt(limits, fraction) {
  const desired = (limits.max - limits.min) * fraction;
  return limits.min + (limits.step ? Math.round(desired / limits.step) * limits.step : desired);
}
async function setControl(page, selector, value) {
  await page.locator(selector).evaluate((el, value) => {
    el.value = String(value); el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true }));
  }, value);
  near(+(await page.locator(selector).inputValue()), value, 1e-9, 'requested control value is reachable');
  await eventually(async () => assert.equal((await time(page)).k, 0), 'control cancels and resets');
  // Allow debouncing a single t=0 plan; do not race a pending reset.
  await page.waitForTimeout(150);
}
async function time(page) {
  const text = (await page.locator(S.t).innerText()).trim();
  const m = text.match(/^Step (\d+) of (\d+)$/);
  assert.ok(m, `step status: ${text}`);
  assert.ok(+m[2] > 0 && +m[1] <= +m[2]);
  return { k: +m[1], n: +m[2], text };
}
async function svgPoints(locator) {
  return locator.evaluate(el => Array.from(el.points, p => [p.x, p.y]));
}
async function scene(page) {
  const views = {};
  for (const name of ['open', 'closed']) {
    const view = page.locator(`[data-wm-view="${name}"]`);
    views[name] = { path: await svgPoints(view.locator('polyline[data-wm-path]')),
      predicted: await svgPoints(view.locator('polyline[data-wm-predicted]')),
      distance: (await view.locator('[data-wm-distance]').innerText()).trim(),
      outcome: (await view.locator('[data-wm-outcome]').innerText()).trim().toLowerCase(),
      plans: numbers(await view.locator('[data-wm-plans]').innerText())[0] };
  }
  return { time: await time(page), views };
}
function runView(raw) {
  const records = Array.isArray(raw) ? raw : pick(raw, 'records', 'steps');
  assert.ok(Array.isArray(records) && records.length > 0, 'executed-step records');
  const plans = raw.plans;
  return records.map(r => {
    const id = pick(r, 'planId', 'planID');
    return { state: pick(r, 'state', 'observedState', 'observed'), action: pick(r, 'action', 'executedAction'),
      next: pick(r, 'nextState', 'trueNextState', 'next'), id,
      plan: r.plan ?? (Array.isArray(plans) ? plans.find(p => (pick(p, 'id', 'planId') ?? plans.indexOf(p)) === id) : plans?.[id]),
      predicted: pick(r, 'predictedPath', 'predicted') };
  });
}
function outcome(records, cfg, finished = true) {
  for (const r of records) {
    if (segmentHits(r.state, r.next, cfg.obstacle)) return 'hit obstacle';
    if (distance(r.next, cfg.goal.center) <= cfg.goal.radius) return 'reached goal';
  }
  return finished ? 'missed goal' : 'running';
}
function auditRun(records, closed, cfg, trueModel, model) {
  vector(records[0].state, cfg.start, 1e-8, 'shared start');
  const ids = new Set();
  let previous;
  for (const [i, r] of records.entries()) {
    assert.ok(r.id !== undefined, 'per-step plan id'); ids.add(r.id);
    if (i) { vector(r.state, records[i - 1].next, 1e-8, 'observed reality'); assert.equal(outcome(records.slice(0, i), cfg, false), 'running', 'terminal runs stop immediately'); }
    vector(r.next, affine(trueModel, r.state, r.action), 1e-8, 'true transition');
    r.action.forEach(a => assert.ok(Math.abs(a) <= cfg.actionLimit + 1e-10));
    if (closed || i === 0) {
      const p = auditPlan(r.plan, model, r.state, cfg);
      vector(r.action, p.actions[0], 1e-8, 'closed executes first action');
      if (closed && previous) {
        vector(pick(p.iterations[0], 'meanBefore', 'mean').slice(0, -1),
          pick(previous.iterations.at(-1), 'meanAfter', 'newMean').slice(1), 1e-8, 'shifted mean warm start');
      }
      previous = p;
    } else vector(r.action, planView(records[0].plan).actions[i], 1e-8, 'open executes original sequence');
    if (r.predicted) vector(points(r.predicted), points(planView(r.plan ?? records[0].plan).path), 1e-7);
  }
  assert.equal(ids.size, closed ? records.length : 1, 'number of plans matches loop structure');
}
async function trueModelFrom(page) {
  // Recover truth from basis probes, rather than trusting the exposed learned fit.
  const queries = [{ state: [0, 0, 0, 0], action: [0, 0] }];
  for (let j = 0; j < 6; j++) {
    const z = Array(6).fill(0); z[j] = 1;
    queries.push({ state: z.slice(0, 4), action: z.slice(4) });
  }
  const next = await page.evaluate(q => q.map(r => Array.from(WorldModel.trueStep(r.state, r.action))), queries);
  return fitAffine(queries.map((r, i) => ({ ...r, nextState: next[i] })));
}
async function fittedTrueModel(page, seed = 1627) {
  const random = rng(seed);
  const queries = Array.from({ length: 80 }, () => ({ state: Array.from({ length: 4 }, () => random() * 8 - 4), action: [random() * 2 - 1, random() * 2 - 1] }));
  const transitions = await page.evaluate(q => q.map(r => ({ ...r, nextState: Array.from(WorldModel.trueStep(r.state, r.action)) })), queries);
  const fitted = await api(page, 'fitDynamics', [transitions]);
  modelNear(fitted, fitAffine(transitions));
  return fitted;
}
async function stepToEnd(page, expected) {
  const snapshots = [await scene(page)], cap = (await time(page)).n;
  for (let i = 0; i < cap; i++) {
    if (Object.values(snapshots.at(-1).views).every(v => v.outcome !== 'running')) break;
    await page.locator(S.step).click();
    await eventually(async () => assert.equal((await time(page)).k, i + 1), 'one discrete step');
    const s = await scene(page);
    if (expected) assertRendered(s, expected, i + 1);
    snapshots.push(s);
  }
  assert.ok(Object.values(snapshots.at(-1).views).every(v => v.outcome !== 'running'), 'both runs terminate');
  const frozen = await scene(page);
  if (await page.locator(S.step).isEnabled()) await page.locator(S.step).click();
  assert.deepEqual(await scene(page), frozen, 'terminal Step does not advance');
  return snapshots;
}
function assertRendered(s, expected, k) {
  for (const name of ['open', 'closed']) {
    const all = expected[name], records = all.slice(0, Math.min(k, all.length)), cfg = expected.cfg;
    const v = s.views[name];
    const actualPoints = [cfg.start.slice(0, 2), ...records.map(r => point(r.next))];
    vector(v.path, actualPoints, 2e-4, `${name} actual SVG`);
    const plan = name === 'open' ? all[0].plan : (records.at(-1) ?? all[0]).plan;
    vector(v.predicted, points(planView(plan).path), 2e-4, `${name} predicted SVG`);
    const position = records.at(-1)?.next ?? cfg.start;
    assert.match(v.distance, /\d+\.\d{2}\b/, 'distance displayed to two decimals');
    near(numbers(v.distance)[0], distance(position, cfg.goal.center), 0.0051, `${name} distance`);
    assert.equal(v.outcome, k === 0 ? 'running' : outcome(records, cfg, records.length === all.length), `${name} truthful geometry outcome`);
    assert.equal(v.plans, name === 'open' ? 1 : Math.max(1, records.length), 'plan count');
  }
}
async function runToEnd(page) {
  const started = performance.now();
  await page.locator(S.run).click();
  await page.waitForFunction(() => [...document.querySelectorAll('[data-wm-outcome]')].length === 2 &&
    [...document.querySelectorAll('[data-wm-outcome]')].every(el => el.textContent.trim().toLowerCase() !== 'running'), null, { timeout: 15000 });
  assert.ok(performance.now() - started < 15000, 'Run completes within 15 seconds');
  return scene(page);
}
async function traceRun(page) {
  // Observe rendered states, not a private UI object or precomputed API result.
  await page.evaluate(() => {
    window.acceptanceRunTrace = [];
    let last = 0;
    window.acceptanceTraceObserver = new MutationObserver(() => {
      const text = document.querySelector('[data-wm-t]').innerText.trim();
      const match = text.match(/^Step (\d+) of (\d+)$/);
      if (!match || +match[1] === last) return;
      last = +match[1];
      const views = {};
      for (const name of ['open', 'closed']) {
        const root = document.querySelector(`[data-wm-view="${name}"]`);
        const pts = selector => Array.from(root.querySelector(selector).points, p => [p.x, p.y]);
        views[name] = { path: pts('polyline[data-wm-path]'), predicted: pts('polyline[data-wm-predicted]'),
          distance: root.querySelector('[data-wm-distance]').innerText.trim(),
          outcome: root.querySelector('[data-wm-outcome]').innerText.trim().toLowerCase(),
          plans: +(root.querySelector('[data-wm-plans]').innerText.match(/\d+/)?.[0]) };
      }
      acceptanceRunTrace.push({ time: { k: +match[1], n: +match[2], text }, views });
    });
    acceptanceTraceObserver.observe(document.getElementById('planner'), { subtree: true, childList: true, characterData: true, attributes: true });
  });
  const end = await runToEnd(page);
  const trace = await page.evaluate(() => { acceptanceTraceObserver.disconnect(); return acceptanceRunTrace; });
  return { end, trace };
}

test('D1: offline self-contained lab, public API and both CI registrations', async t => {
  const page = await pageFor(t);
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'lab');
  assert.equal(await page.locator('html').getAttribute('data-design-system'), 'cursus');
  for (const selector of ['section#planner[data-panel]', 'section#kepler[data-panel]', 'section#agents[data-wm-agents]']) {
    assert.equal(await page.locator(selector).count(), 1); assert.equal(await page.locator(selector).isVisible(), true);
  }
  assert.equal(await page.locator('script[src],script[type="module"],[data-lab],[data-reset],canvas').count(), 0);
  const forbidden = await page.locator('*').evaluateAll(els => els.flatMap(el => [...el.attributes].map(a => a.name)).filter(n => n.startsWith('data-budget')));
  assert.deepEqual(forbidden, []);
  const scripts = await page.locator('script:not([type="application/json"])').allTextContents();
  for (const script of scripts) {
    assert.doesNotMatch(script, /\bfetch\s*\(|\bXMLHttpRequest\b|\bimport\s*\(/, 'no runtime data or module loading');
    assert.doesNotMatch(script, /\bMath\s*\.\s*random\s*\(/, 'seeded randomness');
  }
  for (const method of ['rng', 'trueStep', 'fitDynamics', 'perturb', 'cemPlan', 'runOpenLoop', 'runClosedLoop', 'simulateOrbits', 'fitOrbit', 'predictOrbit']) {
    assert.equal(await page.evaluate(method => typeof WorldModel[method], method), 'function', `WorldModel.${method}`);
  }
  assert.ok(suites.includes('world-model'), 'register world-model in component-helpers suites');
  const pkg = JSON.parse(await readFile(path.join(repoRoot, 'setup/package.json'), 'utf8'));
  const argv = pkg.scripts.test.trim().split(/\s+/);
  assert.deepEqual(argv.slice(0, 2), ['node', '--test']);
  assert.equal(argv.filter(arg => path.resolve(repoRoot, 'setup', arg) === path.join(repoRoot, 'tools/html-pages/tests/world-model.test.mjs')).length, 1,
    'exactly one unfiltered suite registration');
  for (const id of ['planner', 'kepler']) {
    const callout = page.locator(`#${id} .callout[data-illustrative]`);
    assert.equal(await callout.count(), 1); assert.equal(await callout.isVisible(), true);
  }
  for (const url of ['https://arxiv.org/abs/2507.06952', 'https://arxiv.org/abs/2506.09985', 'https://openreview.net/pdf?id=BZ5a1r-kVsf']) {
    assert.ok(await page.locator(`a[href="${url}"]`).count(), `source ${url}`);
  }
});

test('D1: no-JavaScript markup contains both t=0 worlds, baseline orbits, formulas and closing card', async t => {
  const page = await pageFor(t, { javaScriptEnabled: false });
  for (const name of ['open', 'closed']) {
    const view = page.locator(`[data-wm-view="${name}"]`);
    assert.equal(await view.isVisible(), true);
    for (const mark of ['svg', 'circle[data-wm-obstacle]', 'circle[data-wm-goal]', 'polyline[data-wm-path]', 'polyline[data-wm-predicted]']) assert.ok(await view.locator(mark).count(), `static ${name} ${mark}`);
    assert.match(await view.locator('svg').textContent(), /start|initial/i, 'static start position label');
    assert.ok((await view.locator('svg').textContent()).trim().length > 0, 'static SVG text labels or placeholder');
  }
  assert.equal(await page.locator('#kepler polyline[data-kepler-true]').count(), 2);
  assert.equal(await page.locator('#kepler polyline[data-kepler-predicted]').count(), 2);
  for (const poly of await page.locator('#kepler polyline').all()) assert.ok((await svgPoints(poly)).length > 5, 'authored orbital snapshot');
  assert.equal(await page.locator('#agents').isVisible(), true);
  assert.match(await page.locator('body').innerText(), /JavaScript/i, 'visible fallback explanation');
  assert.match(await page.locator('#planner').innerText(), /s\s*[′'’]|s\s*(?:t\s*\+\s*1|_{?t\+1)/i, 'transition equation readable without JS');
});

test('D2: learned affine dynamics recover fresh truth and alternate systems, perturbation leaves truth fixed', async t => {
  const page = await pageFor(t), trueModel = await trueModelFrom(page), fitted = await fittedTrueModel(page);
  modelNear(fitted, trueModel);
  // Damped double integrator: position depends on velocity, acceleration on control.
  assert.ok(trueModel.A[0][2] > 0 && trueModel.A[1][3] > 0, 'position integrates velocity');
  assert.ok(trueModel.A[2][2] > 0 && trueModel.A[2][2] < 1 && trueModel.A[3][3] > 0 && trueModel.A[3][3] < 1, 'positive velocity damping');
  assert.ok(Math.abs(trueModel.B[2][0]) > 0 && Math.abs(trueModel.B[3][1]) > 0, 'controls accelerate');
  for (const seed of [719, 90211, 0xAB19]) {
    const random = rng(seed), unit = () => random() * 2 - 1;
    const alternate = { A: Array.from({ length: 4 }, () => Array.from({ length: 4 }, unit)),
      B: Array.from({ length: 4 }, () => Array.from({ length: 2 }, unit)), c: Array.from({ length: 4 }, unit) };
    const transitions = Array.from({ length: 117 }, () => {
      const state = Array.from({ length: 4 }, unit), action = [unit(), unit()];
      return { state, action, nextState: affine(alternate, state, action) };
    });
    const got = await api(page, 'fitDynamics', [transitions]);
    modelNear(got, alternate); modelNear(got, fitAffine(transitions));
    modelNear(await api(page, 'perturb', [got, 0]), got);
  }
  const before = await api(page, 'trueStep', [[0.27, -0.73, 0.31, -0.12], [0.53, -0.44]]);
  const error = await limits(page, S.error);
  const wrong = await api(page, 'perturb', [fitted, error.max]);
  assert.notDeepEqual(wrong, fitted, 'error changes fitted coefficients');
  assert.notDeepEqual(wrong.B, fitted.B, 'documented control mismatch');
  assert.notDeepEqual(wrong.c, fitted.c, 'documented bias drift');
  assert.deepEqual(await api(page, 'trueStep', [[0.27, -0.73, 0.31, -0.12], [0.53, -0.44]]), before, 'error never changes reality');
  modelNear(await fittedTrueModel(page), fitted, 1e-8);
  const input = page.locator('input[type="range"][data-wm-error]');
  assert.equal(error.min, 0); assert.ok(error.max > 0);
  assert.ok(await input.evaluate(el => [...el.labels].some(l => l.textContent.trim()) || el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')));
  const text = await page.locator('#planner').innerText();
  assert.match(text, /cross[ -]entropy/i);
  const cfg = plannerConfig(await api(page, 'config'));
  for (const key of ['N', 'K', 'I', 'H']) assert.match(text, new RegExp(`\\b${key}\\s*(?:=|:|≈)\\s*${cfg[key]}\\b`), `visible planner ${key}`);
  assert.match(text, /(?:training|train|fitt?ed)[\s\S]*transition|transition[\s\S]*(?:training|train|fitt?ed)/i, 'visible transition-training provenance');
  assert.match(text, /seed/i, 'training seed visible');
  // No special case for exact/noiseless data: the fitter must minimise residuals.
  const random = rng(41779);
  const noisy = Array.from({ length: 151 }, () => {
    const state = Array.from({ length: 4 }, () => random() * 4 - 2), action = [random() * 2 - 1, random() * 2 - 1];
    return { state, action, nextState: affine(trueModel, state, action).map(v => v + (random() - 0.5) * 0.07) };
  });
  modelNear(await api(page, 'fitDynamics', [noisy]), fitAffine(noisy), 1e-7);
});

test('D2: CEM costs, segment collisions, elite means/stds and predictions have independent numerical oracles', async t => {
  const page = await pageFor(t), config = await api(page, 'config'), cfg = plannerConfig(config), model = await fittedTrueModel(page);
  const errors = await limits(page, S.error);
  const seeds = [config.seed, 314159, 27183];
  const plans = [];
  for (const [i, seed] of seeds.entries()) {
    for (const error of [0, errors.default, errors.max]) {
      const perturbed = await api(page, 'perturb', [model, error]);
      // Off-baseline state prevents diagnostics manufactured only for the demonstration.
      const state = cfg.start.map((v, j) => v + (i === 0 ? 0 : (j < 2 ? 0.137 * i : -0.071 * i)));
      const plan = await api(page, 'cemPlan', [perturbed, state, { N: cfg.N, K: cfg.K, I: cfg.I, H: cfg.H, seed }]);
      auditPlan(plan, perturbed, state, cfg);
      assert.deepEqual(await api(page, 'cemPlan', [perturbed, state, { N: cfg.N, K: cfg.K, I: cfg.I, H: cfg.H, seed }]), plan, 'same seed repeats diagnostics');
      plans.push(plan);
    }
  }
  assert.notDeepEqual(plans[0], plans[3], 'different seeds/states produce different searches');
  // Make endpoint-only collision checks observably wrong, using a one-step crossing.
  const mid = cfg.obstacle.center, span = cfg.obstacle.radius * 2.3;
  const crossingModel = { A: [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
    B: [[0, 0], [0, 0], [0, 0], [0, 0]], c: [2 * span, 0, 0, 0] };
  const state = [mid[0] - span, mid[1], 0, 0];
  assert.equal(segmentHits(state, affine(crossingModel, state, [0, 0]), cfg.obstacle), true);
  const crossing = await api(page, 'cemPlan', [crossingModel, state, { N: cfg.N, K: cfg.K, I: cfg.I, H: cfg.H, seed: 4817 }]);
  auditPlan(crossing, crossingModel, state, cfg);
});

test('D2: CEM samples a seeded Gaussian around caller-provided mean/std, rather than uniform search', async t => {
  const page = await pageFor(t), cfg = plannerConfig(await api(page, 'config')), model = await fittedTrueModel(page);
  const local = { ...cfg, N: 2400, K: 24, I: 2, H: 3 };
  const initialMean = Array.from({ length: local.H }, (_, h) => [cfg.actionLimit * (h - 1) * 0.1, cfg.actionLimit * 0.17]);
  const initialStd = Array.from({ length: local.H }, () => [cfg.actionLimit * 0.08, cfg.actionLimit * 0.09]);
  const options = { N: local.N, K: local.K, I: local.I, H: local.H, seed: 847291, initialMean, initialStd };
  const plan = await api(page, 'cemPlan', [model, cfg.start, options]);
  const inspected = auditPlan(plan, model, cfg.start, local), first = inspected.iterations[0];
  vector(pick(first, 'meanBefore', 'mean'), initialMean, 1e-10, 'caller initial mean honoured');
  vector(pick(first, 'stdBefore', 'std'), initialStd, 1e-10, 'caller initial std honoured');
  const samples = pick(first, 'sequences', 'samples', 'sampledSequences');
  for (let h = 0; h < local.H; h++) for (let j = 0; j < 2; j++) {
    const z = samples.map(s => (s[h][j] - initialMean[h][j]) / initialStd[h][j]);
    const mean = z.reduce((s, v) => s + v, 0) / z.length;
    const variance = z.reduce((s, v) => s + (v - mean) ** 2, 0) / z.length;
    const kurtosis = z.reduce((s, v) => s + (v - mean) ** 4, 0) / z.length / variance ** 2;
    // Broad deterministic statistical tolerances permit different Gaussian
    // transforms/caching conventions, but reject uniform or constant sampling.
    near(mean, 0, 0.12, 'Gaussian mean'); near(variance, 1, 0.17, 'Gaussian variance');
    assert.ok(kurtosis > 2.3 && kurtosis < 3.8, `Gaussian fourth moment: ${kurtosis}`);
  }
  assert.deepEqual(await api(page, 'cemPlan', [model, cfg.start, options]), plan, 'Gaussian diagnostics replay exactly');
});

test('D2: genuine open/closed loops, shared initial plan, honest outcomes and demonstration thresholds', async t => {
  const page = await pageFor(t), config = await api(page, 'config'), cfg = plannerConfig(config);
  const trueModel = await trueModelFrom(page), fitted = await fittedTrueModel(page), error = await limits(page, S.error);
  assert.ok(error.default > 0 && error.default <= error.max, 'default demonstrates imperfect model');
  for (const e of [0, error.default, error.max]) {
    const model = await api(page, 'perturb', [fitted, e]);
    const open = runView(await api(page, 'runOpenLoop', [config.seed, e]));
    const closed = runView(await api(page, 'runClosedLoop', [config.seed, e]));
    auditRun(open, false, cfg, trueModel, model); auditRun(closed, true, cfg, trueModel, model);
    vector(planView(open[0].plan).actions, planView(closed[0].plan).actions, 1e-8, 'shared t=0 plan');
    if (e === 0 || e === error.default) assert.equal(outcome(closed, cfg), 'reached goal', 'closed loop reaches without collision');
    if (e === 0) assert.equal(outcome(open, cfg), 'reached goal', 'zero-error open loop reaches without collision');
    if (e === error.default) {
      assert.ok(['hit obstacle', 'missed goal'].includes(outcome(open, cfg)), 'default open loop drifts/fails');
      assert.ok(distance(open.at(-1).next, points(planView(open[0].plan).path).at(-1)) > cfg.goal.radius, 'actual vs predicted open endpoint drifts by more than goal radius');
    }
    await setControl(page, S.error, e);
    const expected = { open, closed, cfg };
    assertRendered(await scene(page), expected, 0);
    await stepToEnd(page, expected);
  }
});

test('D2: side-by-side desktop worlds, stacked 390px worlds, consistent SVG geometry and labelled predictions', async t => {
  const page = await pageFor(t), cfg = plannerConfig(await api(page, 'config'));
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    const open = await page.locator('[data-wm-view="open"]').boundingBox();
    const closed = await page.locator('[data-wm-view="closed"]').boundingBox();
    assert.ok(open && closed);
    if (width === 1440) { near(open.y, closed.y, 4, 'same top edge'); assert.ok(open.x + open.width <= closed.x + 1 || closed.x + closed.width <= open.x + 1, 'non-overlapping columns'); }
    else assert.ok(open.y + open.height <= closed.y + 2, 'stacked views');
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'no horizontal document overflow');
  }
  const scales = [];
  for (const name of ['open', 'closed']) {
    const view = page.locator(`[data-wm-view="${name}"]`);
    scales.push(await view.locator('svg').first().getAttribute('viewBox'));
    for (const [mark, expected] of [['obstacle', cfg.obstacle], ['goal', cfg.goal]]) {
      const c = view.locator(`circle[data-wm-${mark}]`);
      const geom = await c.evaluate(el => [el.cx.baseVal.value, el.cy.baseVal.value, el.r.baseVal.value]);
      vector(geom, [...expected.center, expected.radius]);
    }
    const predicted = view.locator('polyline[data-wm-predicted]');
    assert.ok(await predicted.evaluate(el => !['none', '0px', '0'].includes(getComputedStyle(el).strokeDasharray)), 'prediction dashed');
    assert.match(await view.innerText(), /predict|model/i, 'prediction text legend');
  }
  assert.equal(scales[0], scales[1], 'worlds have identical scale');
});

function orbitConfig(config) {
  const o = pick(config, 'orbit', 'orbits', 'kepler');
  assert.ok(o, 'expose orbit configuration');
  const out = { ...o, centralPosition: pick(o, 'centralPosition', 'center'),
    addedPosition: pick(o, 'addedPosition', 'massPosition'),
    initialStates: pick(o, 'initialStates', 'initialConditions'), times: pick(o, 'times', 'sampleTimes'),
    trainEnd: pick(o, 'trainEnd', 'trainingEnd'), harmonics: pick(o, 'harmonics', 'order') };
  for (const key of ['dt', 'G', 'centralMass', 'softening', 'trainEnd']) assert.ok(Number.isFinite(out[key]) && out[key] > 0, `positive orbit ${key}`);
  assert.equal(out.initialStates.length, 2, 'two test particles');
  out.initialStates.forEach(s => { assert.equal(s.length, 4); s.forEach(v => assert.ok(Number.isFinite(v))); });
  assert.equal(out.centralPosition.length, 2); assert.equal(out.addedPosition.length, 2);
  assert.ok(Number.isInteger(out.harmonics) && out.harmonics > 0 && out.harmonics <= 20, 'bounded truncated Fourier order');
  assert.ok(out.times.length > 20 && out.times.some(t => t > out.trainEnd), 'sampled training and held-out horizon');
  out.times.forEach((t, i) => {
    assert.ok(Number.isFinite(t) && t >= 0 && (!i || t > out.times[i - 1]), 'strict sample times');
    near(t / out.dt, Math.round(t / out.dt), 1e-7, 'fixed-step sample grid');
  });
  return out;
}
// Independent softened Newtonian velocity-Verlet. The moving particles never
// attract each other; the central and added attractors stay fixed.
function orbitOracle(c, mass) {
  const acceleration = position => {
    const out = [0, 0];
    for (const [center, m] of [[c.centralPosition, c.centralMass], [c.addedPosition, mass]]) {
      const d = [center[0] - position[0], center[1] - position[1]];
      const factor = c.G * m / (d[0] ** 2 + d[1] ** 2 + c.softening ** 2) ** 1.5;
      out[0] += factor * d[0]; out[1] += factor * d[1];
    }
    return out;
  };
  return c.initialStates.map(initial => {
    let pos = initial.slice(0, 2), vel = initial.slice(2), a = acceleration(pos), step = 0;
    const result = [];
    for (const time of c.times) {
      const target = Math.round(time / c.dt);
      while (step < target) {
        const next = pos.map((x, j) => x + vel[j] * c.dt + 0.5 * a[j] * c.dt ** 2);
        const b = acceleration(next);
        vel = vel.map((v, j) => v + 0.5 * (a[j] + b[j]) * c.dt);
        pos = next; a = b; step++;
      }
      result.push([...pos]);
    }
    return result;
  });
}
function orbitSeries(raw, c) {
  const orbits = pick(raw, 'orbits', 'trajectories') ?? raw;
  assert.ok(Array.isArray(orbits)); assert.equal(orbits.length, 2);
  return orbits.map(series => {
    const times = pick(series, 'times', 'sampleTimes') ?? c.times;
    vector(times, c.times, 1e-8, 'identical orbit sample times');
    const result = points(pick(series, 'points', 'positions') ?? series);
    assert.equal(result.length, c.times.length);
    return result;
  });
}
function fourierRow(t, period, harmonics) {
  const row = [1];
  for (let h = 1; h <= harmonics; h++) {
    const phase = 2 * Math.PI * h * t / period;
    row.push(Math.cos(phase), Math.sin(phase));
  }
  return row;
}
function orbitFitView(fit) {
  const coeffs = pick(fit, 'coefficients', 'coeffs') ?? [fit.xCoeffs, fit.yCoeffs];
  assert.ok(Number.isFinite(fit.period) && fit.period > 0, 'estimated finite period');
  assert.equal(coeffs.length, 2);
  assert.equal(coeffs[0].length, coeffs[1].length);
  assert.ok(coeffs[0].length >= 3 && coeffs[0].length % 2 === 1, 'truncated Fourier coefficients');
  return { period: fit.period, coefficients: coeffs, harmonics: (coeffs[0].length - 1) / 2 };
}
function evaluateFourier(fit, times) {
  return times.map(t => fit.coefficients.map(coeff => fourierRow(t, fit.period, fit.harmonics).reduce((v, basis, j) => v + basis * coeff[j], 0)));
}
function fitFourierAtPeriod(samples, fit) {
  const rows = samples.map(s => fourierRow(s.t, fit.period, fit.harmonics));
  return [leastSquares(rows, samples.map(s => s.x)), leastSquares(rows, samples.map(s => s.y))];
}
function samplesAt(times, trajectory, predicate = () => true) {
  return times.flatMap((t, i) => predicate(t) ? [{ t, x: trajectory[i][0], y: trajectory[i][1] }] : []);
}
// Extent = largest baseline x/y span (diameter for a circular orbit). The
// held-out error uses the same normalizer for all added-mass settings.
function extent(trajectory) {
  return Math.max(...[0, 1].map(j => Math.max(...trajectory.map(p => p[j])) - Math.min(...trajectory.map(p => p[j]))));
}
function orbitError(truth, predicted, baseline, c) {
  const errors = truth.map((trajectory, j) => Math.max(...trajectory.flatMap((p, i) => c.times[i] > c.trainEnd ? [distance(p, predicted[j][i])] : [])) / extent(baseline[j]));
  errors.forEach(e => assert.ok(Number.isFinite(e) && e >= 0));
  return errors;
}
async function orbitScene(page) {
  const get = selector => page.locator(`#kepler ${selector}`).evaluateAll(els => els.map(el => Array.from(el.points, p => [p.x, p.y])));
  return { truth: await get('polyline[data-kepler-true]'), predicted: await get('polyline[data-kepler-predicted]'),
    error: (await page.locator('[data-kepler-error]').innerText()).trim() };
}
function errorReadout(text, errors) {
  // Either each orbit's error or the worst of the two is sufficient, but the
  // displayed number must be a fraction/percentage of the declared orbit extent.
  const matches = [...text.matchAll(/(\d+(?:\.\d+)?(?:e[-+]?\d+)?)\s*(%|fraction|×|x\b)?/gi)];
  const expected = [Math.max(...errors)];
  assert.ok(matches.some(m => {
    const value = Number(m[1]) / (m[2] === '%' ? 100 : 1);
    const decimals = m[1].split(/[eE]/)[0].split('.')[1]?.length ?? 0;
    const exponent = Number(m[1].split(/[eE]/)[1] ?? 0);
    const rounding = 0.5 * 10 ** (exponent - decimals) / (m[2] === '%' ? 100 : 1) + 1e-8;
    // Prevent a coarse 0 or 1 label from counting as a quantitative error.
    return rounding <= 0.0051 && expected.some(e => Math.abs(e - value) <= rounding);
  }), `error readout must match independently measured fraction: ${text}, expected ${expected}`);
  assert.ok(/[a-z]{3}/i.test(text.replace(/fraction/gi, '')), 'plain-language verdict accompanying error');
}
async function baselineFits(page, c, baseline) {
  const fits = [];
  for (const trajectory of baseline) {
    const samples = samplesAt(c.times, trajectory, t => t <= c.trainEnd);
    assert.ok(samples.length > 2 * c.harmonics + 1, 'overdetermined training fit');
    const raw = await api(page, 'fitOrbit', [samples]), fit = orbitFitView(raw);
    assert.equal(fit.harmonics, c.harmonics, 'page exposes fitted harmonic count');
    vector(fit.coefficients, fitFourierAtPeriod(samples, fit), 2e-6, 'independent baseline least squares');
    const predicted = points(await api(page, 'predictOrbit', [raw, c.times]));
    vector(predicted, evaluateFourier(fit, c.times), 2e-6, 'Fourier predictions from coefficients');
    fits.push({ raw, fit, predicted });
  }
  return fits;
}

test('D3: curve fitter estimates unseen periods and Fourier coefficients from alternate periodic samples', async t => {
  const page = await pageFor(t), c = orbitConfig(await api(page, 'config'));
  for (const seed of [1259, 89981, 73]) {
    const random = rng(seed), period = 3.2 + 4 * random();
    const coeffs = Array.from({ length: 2 }, (_, j) => {
      const row = [0.7 * (random() - 0.5)];
      for (let h = 1; h <= c.harmonics; h++) row.push((j === 0 && h === 1 ? 1.4 : 0.2 / h) * (0.5 + random()),
        (j === 1 && h === 1 ? 1.1 : 0.1 / h) * (0.5 + random()));
      return row;
    });
    const truthFit = { period, harmonics: c.harmonics, coefficients: coeffs };
    const times = Array.from({ length: 361 }, (_, i) => i * period * 4 / 360);
    const samples = samplesAt(times, evaluateFourier(truthFit, times));
    const raw = await api(page, 'fitOrbit', [samples]), fit = orbitFitView(raw);
    near(fit.period, period, period * 0.005, 'unseen fundamental period estimated');
    vector(fit.coefficients, fitFourierAtPeriod(samples, fit), 1e-6, 'alternate least-squares coefficients');
    vector(fit.coefficients, coeffs, 0.04, 'known Fourier coefficients recovered');
    const future = [period * 4.1, period * 4.33, period * 4.89];
    const actual = points(await api(page, 'predictOrbit', [raw, future]));
    vector(actual, evaluateFourier(fit, future), 1e-6, 'alternate predictor implements Fourier equation');
    vector(actual, evaluateFourier(truthFit, future), 0.05, 'held-out synthetic orbit recovered');
  }
});

test('D3: Verlet physics, held-out error thresholds, frozen overlay and honest slider/reset rendering', async t => {
  const page = await pageFor(t), c = orbitConfig(await api(page, 'config')), mass = await limits(page, S.mass);
  const control = page.locator('input[type="range"][data-kepler-mass]');
  assert.equal(mass.min, 0); assert.equal(mass.default, 0); assert.ok(mass.max > 0);
  assert.ok(await control.evaluate(el => [...el.labels].some(l => l.textContent.trim()) || el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')), 'labelled mass control');
  const baseline = orbitOracle(c, 0), fits = await baselineFits(page, c, baseline);
  const predicted = fits.map(f => f.predicted), baseErrors = orbitError(baseline, predicted, baseline, c);
  baseErrors.forEach(e => assert.ok(e < 0.02, `mass-0 held-out error ${e} <2% of orbit extent`));
  let firstDraw, baselineVerdict;
  for (const m of [0, rangeAt(mass, 0.37), mass.max]) {
    const truth = orbitOracle(c, m), errors = orbitError(truth, predicted, baseline, c);
    vector(orbitSeries(await api(page, 'simulateOrbits', [m]), c), truth, 2e-6, 'independent velocity-Verlet physics');
    await setControl(page, S.mass, m);
    const drawn = await orbitScene(page);
    vector(drawn.truth, truth, 2e-4, 'true orbital SVG');
    vector(drawn.predicted, predicted, 2e-4, 'frozen fitted orbital SVG');
    if (firstDraw) assert.deepEqual(drawn.predicted, firstDraw, 'predicted polylines unchanged by new mass');
    else { firstDraw = drawn.predicted; baselineVerdict = drawn.error; }
    errorReadout(drawn.error, errors);
    // Identify the fixed attractor by its world position, allowing a dot, box,
    // cross, diamond or other centred SVG marker, without prescribing its id.
    const markerCount = await page.locator('#kepler svg circle, #kepler svg ellipse, #kepler svg rect, #kepler svg path, #kepler svg polygon, #kepler svg line, #kepler svg use').evaluateAll((els, center) => els.filter(el => {
      const style = getComputedStyle(el), box = el.getBoundingClientRect(), local = el.getBBox();
      return Math.abs(local.x + local.width / 2 - center[0]) < 1e-7 && Math.abs(local.y + local.height / 2 - center[1]) < 1e-7 &&
        style.display !== 'none' && style.visibility !== 'hidden' && +style.opacity > 0 && (box.width > 0 || box.height > 0);
    }).length, c.addedPosition);
    assert.ok(m === 0 ? markerCount === 0 : markerCount > 0, 'added attractor marker iff mass is positive');
    if (m === mass.max) {
      errors.forEach((e, j) => {
        assert.ok(e > 0.10, `added-mass error ${e} >10%`);
        assert.ok(e >= 10 * baseErrors[j], 'added mass breaks frozen predictor by >=10x');
        assert.ok(e >= baseErrors[j], 'error does not decrease min to max');
      });
      assert.notEqual(drawn.error, baselineVerdict, 'quantitative error changes, not merely paths');
    }
  }
  await page.locator(S.reset).click();
  await eventually(async () => assert.equal(+(await control.inputValue()), 0), 'Reset restores mass 0');
  vector((await orbitScene(page)).truth, baseline, 2e-4, 'Reset restores baseline physics');
  const before = await scene(page);
  await setControl(page, S.mass, mass.max);
  assert.equal((await time(page)).k, 0, 'mass input leaves/restarts comparison at t=0');
  // Panel 2 is a static plot: no changes across idle time.
  const staticOrbit = await orbitScene(page);
  await page.waitForTimeout(300);
  assert.deepEqual(await orbitScene(page), staticOrbit);
  assert.deepEqual((await scene(page)).views, before.views, 'adding orbital mass does not change point-mass reality');
});

test('D4: closing card follows both panels, is non-interactive, and has current-hash review evidence', async t => {
  const page = await pageFor(t), card = page.locator('section#agents[data-wm-agents]');
  assert.equal(await card.count(), 1); assert.equal(await card.isVisible(), true);
  assert.equal(await card.evaluate(el => el.closest('[data-panel]') === null &&
    ['planner', 'kepler'].every(id => Boolean(document.getElementById(id).compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING))), true);
  assert.equal(await card.locator('input,button,select,textarea,[contenteditable="true"]').count(), 0);
  const review = await readFile(reviewFile, 'utf8');
  assert.ok(review.includes(sha(await readFile(file))), 'review.md must be bound to current HTML sha256');
  // The reviewer, not token matching, judges mapping clarity, feedback limits,
  // source framing, panel references and agent-neutral applicability.
});

test('A1: mulberry32 stream is reproducible for multiple seeds, including unsigned edge cases', async t => {
  const page = await pageFor(t);
  for (const seed of [0, 1, 42, 0xFFFFFFFF, 0x80F67A10]) {
    const expected = rng(seed), sequence = Array.from({ length: 100 }, expected);
    const actual = await page.evaluate(seed => {
      const random = WorldModel.rng(seed); return Array.from({ length: 100 }, random);
    }, seed);
    vector(actual, sequence, 0, 'mulberry32 exact stream');
  }
});

test('A1: Step, Reset, Run and fresh reloads replay identical runs for three seeds without Math.random', { timeout: 300000 }, async t => {
  const page = await pageFor(t, { viewport: { width: 1280, height: 720 }, reducedMotion: 'no-preference' });
  // Install before reload so transition sampling and initial CEM are covered too.
  await page.addInitScript(() => { Math.random = () => { throw new Error('unseeded Math.random is forbidden'); }; });
  await page.reload();
  await page.waitForFunction(() => window.WorldModel);
  const config = await api(page, 'config'), errors = await limits(page, S.error);
  const mid = rangeAt(errors, 0.5);
  const seedInput = page.locator('input[type="number"][data-wm-seed]');
  assert.equal(await seedInput.count(), 1);
  assert.ok(await seedInput.evaluate(el => [...el.labels].some(l => l.textContent.trim()) || el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')), 'labelled integer seed');
  const distinct = [];
  for (const seed of [config.seed, 17011, 92821]) {
    await setControl(page, S.seed, seed); await setControl(page, S.error, mid);
    assert.equal(+(await page.locator('#planner').getAttribute('data-seed')), seed, 'displayed demonstration seed');
    const start = await scene(page), snapshots = await stepToEnd(page), end = snapshots.at(-1);
    const records = { open: await api(page, 'runOpenLoop', [seed, mid]), closed: await api(page, 'runClosedLoop', [seed, mid]) };
    distinct.push(end.views);
    await page.locator(S.reset).click();
    // Reset retains the currently chosen seed/error; mass returns to its baseline.
    await eventually(async () => assert.deepEqual(await scene(page), start), 'Reset restores identical Step 0');
    const animated = await traceRun(page);
    assert.deepEqual(animated.end, end, 'Run equals Step-to-end');
    assert.deepEqual(animated.trace, snapshots.slice(1), 'Run visits exactly the same per-step states as manual stepping');
    for (let reload = 0; reload < 2; reload++) {
      await page.reload(); await page.waitForFunction(() => window.WorldModel);
      await setControl(page, S.seed, seed); await setControl(page, S.error, mid);
      assert.deepEqual(await scene(page), start, 'fresh load same t=0');
      assert.deepEqual(await stepToEnd(page), snapshots, 'fresh load same per-step states, drawings and readouts');
      assert.deepEqual({ open: await api(page, 'runOpenLoop', [seed, mid]), closed: await api(page, 'runClosedLoop', [seed, mid]) }, records,
        'fresh load identical public run records and plans');
    }
  }
  assert.notDeepEqual(distinct[0], distinct[1], 'different seed changes run');
  assert.notDeepEqual(distinct[1], distinct[2], 'alternate seeds change runs');
});

test('A1: reduced motion starts and stays in Step mode, and switching preference cancels an active Run', async t => {
  const page = await pageFor(t, { reducedMotion: 'reduce' });
  const run = page.locator(S.run);
  assert.ok(!(await run.isVisible()) || !(await run.isEnabled()), 'Run unavailable under reduced motion');
  assert.equal((await page.locator('[data-wm-mode]').innerText()).trim(), 'Step mode (reduced motion)');
  const initial = await scene(page);
  await page.waitForTimeout(1000); assert.deepEqual(await scene(page), initial, 'paused while idle');
  for (let i = 0; i < 3; i++) {
    const before = await time(page);
    if (Object.values((await scene(page)).views).every(v => v.outcome !== 'running')) break;
    await page.locator(S.step).click();
    await eventually(async () => assert.equal((await time(page)).k, before.k + 1), 'Step changes k by exactly 1');
    const after = await scene(page); await page.waitForTimeout(300);
    assert.deepEqual(await scene(page), after, 'only manual Step changes state');
  }
  await page.locator(S.reset).click();
  await eventually(async () => assert.deepEqual(await scene(page), initial), 'reduced motion reset');
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await eventually(async () => { assert.equal(await run.isVisible(), true); assert.equal(await run.isEnabled(), true); });
  await run.click();
  await page.waitForFunction(() => /Step [1-9]\d* of/.test(document.querySelector('[data-wm-t]').textContent));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await eventually(async () => assert.ok(!(await run.isVisible()) || !(await run.isEnabled())));
  const stopped = await scene(page); await page.waitForTimeout(1000);
  assert.deepEqual(await scene(page), stopped, 'media-query change stops further advancement');
  assert.equal((await page.locator('[data-wm-mode]').innerText()).trim(), 'Step mode (reduced motion)');
});

test('A1: changing error, seed or mass during Run cancels pending work and restarts at Step 0', async t => {
  const page = await pageFor(t, { reducedMotion: 'no-preference' });
  const error = await limits(page, S.error), mass = await limits(page, S.mass), config = await api(page, 'config');
  for (const [selector, value] of [[S.error, error.max], [S.seed, config.seed + 37], [S.mass, mass.max]]) {
    await page.locator(S.run).click();
    await page.waitForFunction(() => /Step [1-9]\d* of/.test(document.querySelector('[data-wm-t]').textContent));
    await setControl(page, selector, value);
    const reset = await scene(page);
    assert.equal(reset.time.k, 0);
    await page.waitForTimeout(350);
    assert.deepEqual(await scene(page), reset, 'stale frames never restart a cancelled run');
  }
});

test('A1: bounded input handlers and max-error Run have zero >50ms long tasks and finish within 15s', { timeout: 25000 }, async t => {
  const page = await pageFor(t, { viewport: { width: 1280, height: 720 }, reducedMotion: 'no-preference' });
  assert.ok(await page.evaluate(() => PerformanceObserver.supportedEntryTypes.includes('longtask')), 'Chromium must support long-task measurement');
  await page.evaluate(() => {
    window.acceptanceLongTasks = [];
    window.acceptanceObserver = new PerformanceObserver(list => acceptanceLongTasks.push(...list.getEntries().map(e => e.duration)));
    acceptanceObserver.observe({ type: 'longtask' });
    window.acceptanceInputCalls = [];
    for (const name of ['runOpenLoop', 'runClosedLoop']) {
      const original = WorldModel[name];
      WorldModel[name] = function (...args) { acceptanceInputCalls.push(name); return original.apply(this, args); };
    }
  });
  const error = await limits(page, S.error);
  await setControl(page, S.error, error.max);
  assert.deepEqual(await page.evaluate(() => acceptanceInputCalls), [], 'input does not compute whole trajectories synchronously or in deferred reset');
  await page.locator(S.reset).click();
  await eventually(async () => assert.equal((await time(page)).k, 0));
  await runToEnd(page);
  await page.waitForTimeout(100); // Deliver observer batches after the last frame.
  const tasks = await page.evaluate(() => {
    acceptanceLongTasks.push(...acceptanceObserver.takeRecords().map(e => e.duration));
    acceptanceObserver.disconnect(); return acceptanceLongTasks;
  });
  assert.deepEqual(tasks.filter(duration => duration > 50), [], `max-error Run/input long tasks: ${tasks}`);
  const review = await readFile(reviewFile, 'utf8');
  assert.ok(review.includes(sha(await readFile(file))), 'performance/screenshot evidence bound to final page');
  // Evidence presence only; the cross-vendor reviewer checks measured values,
  // environment, safety margin and actual screenshot inspection notes.
  assert.match(review, /(?:4\s*[×x]|four.?times|4.?fold)/i, 'record one-shot 4x CPU throttle');
  assert.match(review, /\d+(?:\.\d+)?\s*ms\b/i, 'record measured planning/frame timings');
  assert.match(review, /margin/i, 'record timing safety margin');
});
