// Shared by world-model.test.mjs and world-model-replay.test.mjs: the lab's page helpers and
// the independent numerical oracles. Not a suite (suites end in .test.mjs).
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from '../browser.mjs';
import { repoRoot, openPage, eventually } from './component-helpers.mjs';


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
 * Prose/source accuracy is reviewed by a person; this suite checks structure.
 */
export const relative = 'sessions/01-fundamentals/cursus/labs/world-model';
export const file = path.join(repoRoot, `${relative}.html`);
export const S = { error: '[data-wm-error]', seed: '[data-wm-seed]', mass: '[data-kepler-mass]',
  step: '[data-wm-step]', run: '[data-wm-run]', reset: '[data-wm-reset]', t: '[data-wm-t]' };
export const pick = (o, ...keys) => keys.map(k => o?.[k]).find(v => v !== undefined);
export const numbers = text => (text.match(/[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?/gi) || []).map(Number);
export const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
export const point = p => Array.isArray(p) ? p.slice(0, 2) : [p.x, p.y];
export const points = p => (pick(p, 'points', 'path', 'predictedPath') ?? p).map(point);
export function near(a, b, tolerance = 1e-8, label = 'number') {
  assert.ok(Number.isFinite(a) && Number.isFinite(b), `${label}: finite (${a}, ${b})`);
  assert.ok(Math.abs(a - b) <= tolerance, `${label}: ${a} != ${b}, tolerance ${tolerance}`);
}
export function vector(a, b, tolerance = 1e-8, label = 'vector') {
  assert.ok(Array.isArray(a) && Array.isArray(b), `${label}: arrays`);
  assert.equal(a.length, b.length, `${label}: length`);
  a.forEach((v, i) => Array.isArray(b[i]) ? vector(v, b[i], tolerance, `${label}[${i}]`) : near(v, b[i], tolerance, `${label}[${i}]`));
}
export function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6D2B79F5) >>> 0;
    let v = Math.imul(s ^ (s >>> 15), s | 1);
    v ^= v + Math.imul(v ^ (v >>> 7), v | 61);
    return ((v ^ (v >>> 14)) >>> 0) / 4294967296;
  };
}
export function affine(model, state, action) {
  return model.A.map((row, i) => row.reduce((v, a, j) => v + a * state[j], model.c[i]) +
    model.B[i].reduce((v, b, j) => v + b * action[j], 0));
}
// Pivoted elimination of normal equations, independent of the page's fitter.
export function leastSquares(rows, values) {
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
export function fitAffine(transitions) {
  const rows = transitions.map(r => [...r.state, ...r.action, 1]);
  const coeffs = Array.from({ length: 4 }, (_, i) => leastSquares(rows, transitions.map(r => r.nextState[i])));
  return { A: coeffs.map(r => r.slice(0, 4)), B: coeffs.map(r => r.slice(4, 6)), c: coeffs.map(r => r[6]) };
}
export function modelNear(a, b, tolerance = 1e-8) {
  for (const key of ['A', 'B', 'c']) vector(a[key], b[key], tolerance, key);
}
export function segmentHits(a, b, circle) {
  const dx = b[0] - a[0], dy = b[1] - a[1], d2 = dx * dx + dy * dy;
  const t = d2 === 0 ? 0 : Math.max(0, Math.min(1, ((circle.center[0] - a[0]) * dx + (circle.center[1] - a[1]) * dy) / d2));
  return distance([a[0] + t * dx, a[1] + t * dy], circle.center) <= circle.radius;
}
export function circle(c) {
  assert.ok(c, 'expose circle geometry in config');
  return { center: pick(c, 'center', 'position') ?? [c.x, c.y], radius: pick(c, 'radius', 'r') };
}
export function plannerConfig(c) {
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
export function rollout(model, state, actions) {
  const states = [state];
  for (const u of actions) states.push(affine(model, states.at(-1), u));
  return states;
}
export function cost(model, state, actions, cfg) {
  const states = rollout(model, state, actions);
  const hits = states.slice(1).reduce((n, s, i) => n + Number(segmentHits(states[i], s, cfg.obstacle)), 0);
  const effort = actions.flat().reduce((n, u) => n + u * u, 0);
  return cfg.weights.goal * distance(states.at(-1), cfg.goal.center) + cfg.weights.obstacle * hits + cfg.weights.effort * effort;
}
export function planView(p) {
  assert.ok(p, 'each computed plan must be inspectable');
  return { raw: p, state: pick(p, 'state', 'startState', 'observedState'), actions: pick(p, 'actions', 'sequence'),
    path: pick(p, 'predictedPath', 'predicted', 'path'), iterations: pick(p, 'iterations', 'diagnostics') };
}
export function auditPlan(raw, model, state, cfg) {
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

export async function pageFor(t, options = {}) {
  const page = await openPage(t, chromium, { file, offline: true, ...options });
  if (options.javaScriptEnabled !== false) {
    await page.waitForFunction(() => window.WorldModel && typeof WorldModel.cemPlan === 'function');
    await eventually(async () => assert.equal((await time(page)).k, 0), 'initial paused scene');
  }
  return page;
}
export async function api(page, method, args = []) {
  return page.evaluate(({ method, args }) => {
    const result = method === 'config' ? WorldModel.config : WorldModel[method](...args);
    return JSON.parse(JSON.stringify(result, (_key, value) => ArrayBuffer.isView(value) ? Array.from(value) : value));
  }, { method, args });
}
export async function limits(page, selector) {
  return page.locator(selector).evaluate(el => ({ min: +el.min, max: +el.max, step: el.step === 'any' ? 0 : +(el.step || 1), value: +el.value, default: +el.defaultValue }));
}
export function rangeAt(limits, fraction) {
  const desired = (limits.max - limits.min) * fraction;
  return limits.min + (limits.step ? Math.round(desired / limits.step) * limits.step : desired);
}
export async function setControl(page, selector, value) {
  await page.locator(selector).evaluate((el, value) => {
    el.value = String(value); el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true }));
  }, value);
  near(+(await page.locator(selector).inputValue()), value, 1e-9, 'requested control value is reachable');
  await eventually(async () => assert.equal((await time(page)).k, 0), 'control cancels and resets');
  // Allow debouncing a single t=0 plan; do not race a pending reset.
  await page.waitForTimeout(150);
}
export async function time(page) {
  const text = (await page.locator(S.t).innerText()).trim();
  const m = text.match(/^Step (\d+) of (\d+)$/);
  assert.ok(m, `step status: ${text}`);
  assert.ok(+m[2] > 0 && +m[1] <= +m[2]);
  return { k: +m[1], n: +m[2], text };
}
export async function svgPoints(locator) {
  return locator.evaluate(el => Array.from(el.points, p => [p.x, p.y]));
}
export async function scene(page) {
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
export function runView(raw) {
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
export function outcome(records, cfg, finished = true) {
  for (const r of records) {
    if (segmentHits(r.state, r.next, cfg.obstacle)) return 'hit obstacle';
    if (distance(r.next, cfg.goal.center) <= cfg.goal.radius) return 'reached goal';
  }
  return finished ? 'missed goal' : 'running';
}
export function auditRun(records, closed, cfg, trueModel, model) {
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
export async function trueModelFrom(page) {
  // Recover truth from basis probes, rather than trusting the exposed learned fit.
  const queries = [{ state: [0, 0, 0, 0], action: [0, 0] }];
  for (let j = 0; j < 6; j++) {
    const z = Array(6).fill(0); z[j] = 1;
    queries.push({ state: z.slice(0, 4), action: z.slice(4) });
  }
  const next = await page.evaluate(q => q.map(r => Array.from(WorldModel.trueStep(r.state, r.action))), queries);
  return fitAffine(queries.map((r, i) => ({ ...r, nextState: next[i] })));
}
export async function fittedTrueModel(page, seed = 1627) {
  const random = rng(seed);
  const queries = Array.from({ length: 80 }, () => ({ state: Array.from({ length: 4 }, () => random() * 8 - 4), action: [random() * 2 - 1, random() * 2 - 1] }));
  const transitions = await page.evaluate(q => q.map(r => ({ ...r, nextState: Array.from(WorldModel.trueStep(r.state, r.action)) })), queries);
  const fitted = await api(page, 'fitDynamics', [transitions]);
  modelNear(fitted, fitAffine(transitions));
  return fitted;
}
export async function stepToEnd(page, expected) {
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
export function assertRendered(s, expected, k) {
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
export async function runToEnd(page) {
  const started = performance.now();
  await page.locator(S.run).click();
  await page.waitForFunction(() => [...document.querySelectorAll('[data-wm-outcome]')].length === 2 &&
    [...document.querySelectorAll('[data-wm-outcome]')].every(el => el.textContent.trim().toLowerCase() !== 'running'), null, { timeout: 15000 });
  assert.ok(performance.now() - started < 15000, 'Run completes within 15 seconds');
  return scene(page);
}
export async function traceRun(page) {
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
