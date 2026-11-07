import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../../../../tools/html-pages/browser.mjs';
import { repoRoot, eventually } from '../../../../tools/html-pages/tests/component-helpers.mjs';

/* The world-model lab: a point mass steered by a CEM planner through a learned affine model (open
 * loop vs closed loop), and a frozen Fourier fit of two orbits that breaks when a mass is added.
 * Every number is checked against an independent oracle in this file, and the drawing against the
 * page's own public API (window.WorldModel). Field-name aliases (pick) tolerate the API's
 * alternate spellings: states/actions are [x,y,vx,vy]/[ux,uy]; fitDynamics returns {A,B,c};
 * cemPlan returns {state,actions,predictedPath,iterations}; run{Open,Closed}Loop returns
 * per-step records {state,action,nextState,planId,plan} (or {records,plans}). Layout, axe, no-JS
 * and reduced-motion CSS are check-page.mjs's job. */
const file = path.join(repoRoot, 'sessions/01-fundamentals/cursus/labs/world-model.html');
const S = { error: '[data-wm-error]', seed: '[data-wm-seed]', mass: '[data-kepler-mass]',
  step: '[data-wm-step]', run: '[data-wm-run]', reset: '[data-wm-reset]', t: '[data-wm-t]' };

// ---- One browser for the file, a fresh context per test. ----
let browser;
after(() => browser?.close());

async function pageFor(t, { reducedMotion = 'no-preference' } = {}) {
  browser ??= await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, reducedMotion });
  const errors = [];
  t.after(async () => { await context.close(); assert.deepEqual(errors, [], 'no runtime errors or remote requests'); });
  await context.route(/^(https?|wss?):/i, route => { errors.push(`remote request: ${route.request().url()}`); return route.abort(); });
  await context.addInitScript(() => {
    // Every random draw must come from the page's seeded generator, so each run replays exactly.
    Math.random = () => { throw new Error('unseeded Math.random is forbidden'); };
    // One round trip per snapshot of what the planner panel draws.
    window.__wmScene = () => {
      const text = document.querySelector('[data-wm-t]').innerText.trim();
      const m = text.match(/^Step (\d+) of (\d+)$/), views = {};
      for (const name of ['open', 'closed']) {
        const root = document.querySelector(`[data-wm-view="${name}"]`);
        const pts = selector => Array.from(root.querySelector(selector).points, p => [p.x, p.y]);
        views[name] = { path: pts('polyline[data-wm-path]'), predicted: pts('polyline[data-wm-predicted]'),
          distance: root.querySelector('[data-wm-distance]').innerText.trim(),
          outcome: root.querySelector('[data-wm-outcome]').innerText.trim().toLowerCase(),
          plans: Number(root.querySelector('[data-wm-plans]').innerText.match(/\d+/)?.[0]) };
      }
      return { time: m ? { k: +m[1], n: +m[2], text } : { text }, views };
    };
  });
  const page = await context.newPage();
  page.setDefaultTimeout(4000);
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(pathToFileURL(file).href);
  await page.waitForFunction(() => window.WorldModel && typeof WorldModel.cemPlan === 'function');
  await eventually(async () => assert.equal((await time(page)).k, 0), 'initial paused scene');
  return page;
}

// ---- Independent numerical oracles. Messages are built only on failure: audits compare ~10^6 numbers. ----
const pick = (o, ...keys) => keys.map(k => o?.[k]).find(v => v !== undefined);
const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const point = p => Array.isArray(p) ? p.slice(0, 2) : [p.x, p.y];
const points = p => (pick(p, 'points', 'path', 'predictedPath') ?? p).map(point);
const close = (a, b, tolerance) => typeof a === 'number' && typeof b === 'number' && Math.abs(a - b) <= tolerance;
function near(a, b, tolerance = 1e-8, label = 'number') {
  if (close(a, b, tolerance)) return;
  assert.ok(Number.isFinite(a) && Number.isFinite(b), `${label}: finite (${a}, ${b})`);
  assert.fail(`${label}: ${a} != ${b}, tolerance ${tolerance}`);
}
function vector(a, b, tolerance = 1e-8, label = 'vector') {
  if (!Array.isArray(a) || !Array.isArray(b)) assert.fail(`${label}: arrays`);
  if (a.length !== b.length) assert.fail(`${label}: length ${a.length} != ${b.length}`);
  for (let i = 0; i < a.length; i++) {
    if (Array.isArray(b[i])) vector(a[i], b[i], tolerance, `${label}[${i}]`);
    else if (!close(a[i], b[i], tolerance)) near(a[i], b[i], tolerance, `${label}[${i}]`);
  }
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
// Cost = goal weight * terminal distance + obstacle weight * segment-circle hits + effort weight * sum(u^2).
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
// Re-scores every sampled sequence, re-selects the elites and recomputes the mean/std update.
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
    assert.equal(before.length, cfg.H); assert.equal(beforeStd.length, cfg.H);
    if (prior) { vector(before, prior.mean, 1e-8, 'refitted mean used next'); vector(beforeStd, prior.std, 1e-8, 'refitted std used next'); }
    const expectedCosts = samples.map(sequence => {
      assert.equal(sequence.length, cfg.H);
      for (const u of sequence) {
        assert.equal(u.length, 2);
        for (const a of u) if (!(Number.isFinite(a) && Math.abs(a) <= cfg.actionLimit + 1e-10)) assert.fail(`sampled action ${a} out of bounds`);
      }
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
    assert.ok(new Set(samples.map(s => JSON.stringify(s))).size > cfg.K, 'genuine varied sampled search');
    prior = { mean: after, std: afterStd, samples };
  }
  const selected = pick(raw, 'selectedIndex', 'bestIndex');
  vector(p.actions, selected === undefined ? prior.mean : prior.samples[selected], 1e-8, 'executed sequence comes from CEM');
  vector(points(p.path), rollout(model, state, p.actions).map(point), 1e-7, 'predicted path rolled through learned model');
  return p;
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
// Open loop: one plan executed blind. Closed loop: a fresh CEM plan from each observed state,
// warm-started from the previous plan shifted by one step.
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

// ---- Page access. ----
async function api(page, method, args = []) {
  // A JSON string crosses the protocol much faster than a structured clone of a closed-loop run.
  return JSON.parse(await page.evaluate(({ method, args }) => {
    const result = method === 'config' ? WorldModel.config : WorldModel[method](...args);
    return JSON.stringify(result, (_key, value) => ArrayBuffer.isView(value) ? Array.from(value) : value);
  }, { method, args }));
}
async function limits(page, selector) {
  return page.locator(selector).evaluate(el => ({ min: +el.min, max: +el.max, value: +el.value, default: +el.defaultValue }));
}
async function time(page) {
  const text = (await page.locator(S.t).innerText()).trim();
  const m = text.match(/^Step (\d+) of (\d+)$/);
  assert.ok(m, `step status: ${text}`);
  assert.ok(+m[2] > 0 && +m[1] <= +m[2]);
  return { k: +m[1], n: +m[2], text };
}
const scene = page => page.evaluate(() => window.__wmScene());
const finished = s => Object.values(s.views).every(v => v.outcome !== 'running');
async function setControl(page, selector, value) {
  await page.locator(selector).evaluate((el, value) => {
    el.value = String(value); el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true }));
  }, value);
  near(+(await page.locator(selector).inputValue()), value, 1e-9, 'requested control value is reachable');
  // The page draws Step 0 at once and plans it on the next animation frame.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal((await time(page)).k, 0, 'a control change restarts at Step 0');
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
// The drawing at step k equals the records: actual path, current plan's prediction, distance, outcome, plan count.
function assertRendered(s, expected, k) {
  for (const name of ['open', 'closed']) {
    const all = expected[name], records = all.slice(0, Math.min(k, all.length)), cfg = expected.cfg;
    const v = s.views[name];
    vector(v.path, [cfg.start.slice(0, 2), ...records.map(r => point(r.next))], 2e-4, `${name} actual SVG`);
    const plan = name === 'open' ? all[0].plan : (records.at(-1) ?? all[0]).plan;
    vector(v.predicted, points(planView(plan).path), 2e-4, `${name} predicted SVG`);
    near(Number(v.distance), distance(records.at(-1)?.next ?? cfg.start, cfg.goal.center), 0.0051, `${name} distance`);
    assert.equal(v.outcome, k === 0 ? 'running' : outcome(records, cfg, records.length === all.length), `${name} truthful geometry outcome`);
    assert.equal(v.plans, name === 'open' ? 1 : Math.max(1, records.length), 'plan count');
  }
}
async function stepToEnd(page, expected) {
  const snapshots = [await scene(page)];
  for (let i = 0; i < snapshots[0].time.n && !finished(snapshots.at(-1)); i++) {
    await page.locator(S.step).click();
    const s = await scene(page); // the Step handler renders synchronously
    assert.equal(s.time.k, i + 1, 'one discrete step');
    if (expected) assertRendered(s, expected, i + 1);
    snapshots.push(s);
  }
  assert.ok(finished(snapshots.at(-1)), 'both runs terminate');
  if (await page.locator(S.step).isEnabled()) await page.locator(S.step).click();
  assert.deepEqual(await scene(page), snapshots.at(-1), 'terminal Step does not advance');
  return snapshots;
}
// Records every state the animated Run draws, as it draws it.
async function traceRun(page) {
  await page.evaluate(() => {
    window.__wmTrace = [];
    let last = 0;
    window.__wmObserver = new MutationObserver(() => {
      const s = window.__wmScene();
      if (s.time.k === undefined || s.time.k === last) return;
      last = s.time.k;
      window.__wmTrace.push(s);
    });
    window.__wmObserver.observe(document.getElementById('planner'), { subtree: true, childList: true, characterData: true, attributes: true });
  });
  await page.locator(S.run).click();
  await page.waitForFunction(() => [...document.querySelectorAll('[data-wm-outcome]')].length === 2 &&
    [...document.querySelectorAll('[data-wm-outcome]')].every(el => el.textContent.trim().toLowerCase() !== 'running'), null, { timeout: 15000 });
  const trace = await page.evaluate(() => { window.__wmObserver.disconnect(); return window.__wmTrace; });
  return { end: await scene(page), trace };
}
const waitRunning = page => page.waitForFunction(() => /Step [1-9]\d* of/.test(document.querySelector('[data-wm-t]').textContent));

// ---- Panel 1: learned dynamics, CEM, open vs closed loop. ----

test('fitDynamics recovers the true dynamics and alternate systems; model error perturbs the model, never reality', async t => {
  const page = await pageFor(t), trueModel = await trueModelFrom(page), fitted = await fittedTrueModel(page);
  modelNear(fitted, trueModel);
  // Damped double integrator: position integrates velocity, controls accelerate.
  assert.ok(trueModel.A[0][2] > 0 && trueModel.A[1][3] > 0, 'position integrates velocity');
  assert.ok(trueModel.A[2][2] > 0 && trueModel.A[2][2] < 1 && trueModel.A[3][3] > 0 && trueModel.A[3][3] < 1, 'positive velocity damping');
  assert.ok(Math.abs(trueModel.B[2][0]) > 0 && Math.abs(trueModel.B[3][1]) > 0, 'controls accelerate');
  const random = rng(719), unit = () => random() * 2 - 1;
  const alternate = { A: Array.from({ length: 4 }, () => Array.from({ length: 4 }, unit)),
    B: Array.from({ length: 4 }, () => Array.from({ length: 2 }, unit)), c: Array.from({ length: 4 }, unit) };
  const transitions = Array.from({ length: 117 }, () => {
    const state = Array.from({ length: 4 }, unit), action = [unit(), unit()];
    return { state, action, nextState: affine(alternate, state, action) };
  });
  const got = await api(page, 'fitDynamics', [transitions]);
  modelNear(got, alternate);
  modelNear(await api(page, 'perturb', [got, 0]), got);
  // The fitter minimises residuals rather than special-casing exact data.
  const noiseRandom = rng(41779);
  const noisy = Array.from({ length: 151 }, () => {
    const state = Array.from({ length: 4 }, () => noiseRandom() * 4 - 2), action = [noiseRandom() * 2 - 1, noiseRandom() * 2 - 1];
    return { state, action, nextState: affine(trueModel, state, action).map(v => v + (noiseRandom() - 0.5) * 0.07) };
  });
  modelNear(await api(page, 'fitDynamics', [noisy]), fitAffine(noisy), 1e-7);
  const probe = [[0.27, -0.73, 0.31, -0.12], [0.53, -0.44]];
  const before = await api(page, 'trueStep', probe);
  const error = await limits(page, S.error);
  assert.equal(error.min, 0); assert.ok(error.max > 0);
  const wrong = await api(page, 'perturb', [fitted, error.max]);
  assert.notDeepEqual(wrong.B, fitted.B, 'model error mismatches the controls');
  assert.notDeepEqual(wrong.c, fitted.c, 'model error adds a drift');
  assert.deepEqual(await api(page, 'trueStep', probe), before, 'model error never changes reality');
});

test('CEM: costs, segment collisions, elite updates and predicted paths match independent oracles', async t => {
  const page = await pageFor(t), config = await api(page, 'config'), cfg = plannerConfig(config), model = await fittedTrueModel(page);
  const errors = await limits(page, S.error), options = seed => ({ N: cfg.N, K: cfg.K, I: cfg.I, H: cfg.H, seed });
  // The demonstration, and an off-baseline state and seed at maximum error.
  const cases = [
    { seed: config.seed, error: errors.default, state: cfg.start },
    { seed: 314159, error: errors.max, state: cfg.start.map((v, j) => v + (j < 2 ? 0.137 : -0.071)) },
  ];
  const plans = [];
  for (const { seed, error, state } of cases) {
    const perturbed = await api(page, 'perturb', [model, error]);
    const plan = await api(page, 'cemPlan', [perturbed, state, options(seed)]);
    auditPlan(plan, perturbed, state, cfg);
    plans.push({ plan, args: [perturbed, state, options(seed)] });
  }
  assert.deepEqual(await api(page, 'cemPlan', plans[1].args), plans[1].plan, 'same seed repeats the search exactly');
  assert.notDeepEqual(plans[0].plan, plans[1].plan, 'different seeds/states produce different searches');
  // A one-step jump across the obstacle: an endpoint-only collision check would miss it.
  const mid = cfg.obstacle.center, span = cfg.obstacle.radius * 2.3;
  const crossingModel = { A: [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
    B: [[0, 0], [0, 0], [0, 0], [0, 0]], c: [2 * span, 0, 0, 0] };
  const state = [mid[0] - span, mid[1], 0, 0];
  assert.equal(segmentHits(state, affine(crossingModel, state, [0, 0]), cfg.obstacle), true);
  auditPlan(await api(page, 'cemPlan', [crossingModel, state, options(4817)]), crossingModel, state, cfg);
});

test('CEM samples a seeded Gaussian around the caller-provided mean/std, not a uniform search', async t => {
  const page = await pageFor(t), cfg = plannerConfig(await api(page, 'config')), model = await fittedTrueModel(page);
  const local = { ...cfg, N: 2400, K: 24, I: 2, H: 3 };
  const initialMean = Array.from({ length: local.H }, (_, h) => [cfg.actionLimit * (h - 1) * 0.1, cfg.actionLimit * 0.17]);
  const initialStd = Array.from({ length: local.H }, () => [cfg.actionLimit * 0.08, cfg.actionLimit * 0.09]);
  const options = { N: local.N, K: local.K, I: local.I, H: local.H, seed: 847291, initialMean, initialStd };
  const plan = await api(page, 'cemPlan', [model, cfg.start, options]);
  const first = auditPlan(plan, model, cfg.start, local).iterations[0];
  vector(pick(first, 'meanBefore', 'mean'), initialMean, 1e-10, 'caller initial mean honoured');
  vector(pick(first, 'stdBefore', 'std'), initialStd, 1e-10, 'caller initial std honoured');
  const samples = pick(first, 'sequences', 'samples', 'sampledSequences');
  for (let h = 0; h < local.H; h++) for (let j = 0; j < 2; j++) {
    const z = samples.map(s => (s[h][j] - initialMean[h][j]) / initialStd[h][j]);
    const mean = z.reduce((s, v) => s + v, 0) / z.length;
    const variance = z.reduce((s, v) => s + (v - mean) ** 2, 0) / z.length;
    const kurtosis = z.reduce((s, v) => s + (v - mean) ** 4, 0) / z.length / variance ** 2;
    // Broad tolerances allow any Gaussian transform but reject uniform or constant sampling.
    near(mean, 0, 0.12, 'Gaussian mean'); near(variance, 1, 0.17, 'Gaussian variance');
    assert.ok(kurtosis > 2.3 && kurtosis < 3.8, `Gaussian fourth moment: ${kurtosis}`);
  }
});

test('open vs closed loop: real plans and honest outcomes, drawn step by step; Reset and Run replay them; the seed changes them', { timeout: 60000 }, async t => {
  const page = await pageFor(t), config = await api(page, 'config'), cfg = plannerConfig(config);
  const trueModel = await trueModelFrom(page), fitted = await fittedTrueModel(page), error = await limits(page, S.error);
  assert.ok(error.default > 0 && error.default <= error.max, 'the default demonstrates an imperfect model');
  assert.equal(error.value, error.default, 'the page opens on the demonstration error');
  let expected;
  for (const e of [0, error.default]) {
    const model = await api(page, 'perturb', [fitted, e]);
    const open = runView(await api(page, 'runOpenLoop', [config.seed, e]));
    const closed = runView(await api(page, 'runClosedLoop', [config.seed, e]));
    auditRun(open, false, cfg, trueModel, model); auditRun(closed, true, cfg, trueModel, model);
    vector(planView(open[0].plan).actions, planView(closed[0].plan).actions, 1e-8, 'shared t=0 plan');
    assert.equal(outcome(closed, cfg), 'reached goal', 'the closed loop reaches the goal without collision');
    if (e === 0) assert.equal(outcome(open, cfg), 'reached goal', 'with a perfect model the open loop reaches too');
    else {
      assert.ok(['hit obstacle', 'missed goal'].includes(outcome(open, cfg)), 'the default open loop fails');
      assert.ok(distance(open.at(-1).next, points(planView(open[0].plan).path).at(-1)) > cfg.goal.radius,
        'the open loop drifts from its prediction by more than the goal radius');
    }
    expected = { open, closed, cfg };
  }
  // Obstacle and goal are drawn where the physics puts them, at the same scale in both worlds.
  const drawn = await page.evaluate(() => ['open', 'closed'].map(name => {
    const view = document.querySelector(`[data-wm-view="${name}"]`), geom = el => [el.cx.baseVal.value, el.cy.baseVal.value, el.r.baseVal.value];
    return { viewBox: view.querySelector('svg').getAttribute('viewBox'),
      obstacle: geom(view.querySelector('circle[data-wm-obstacle]')), goal: geom(view.querySelector('circle[data-wm-goal]')) };
  }));
  assert.equal(drawn[0].viewBox, drawn[1].viewBox, 'worlds have identical scale');
  for (const view of drawn) {
    vector(view.obstacle, [...cfg.obstacle.center, cfg.obstacle.radius], 1e-8, 'drawn obstacle');
    vector(view.goal, [...cfg.goal.center, cfg.goal.radius], 1e-8, 'drawn goal');
  }
  const start = await scene(page);
  assertRendered(start, expected, 0);
  const stepped = await stepToEnd(page, expected);
  await page.locator(S.reset).click();
  await eventually(async () => assert.deepEqual(await scene(page), start), 'Reset restores Step 0');
  const run = await traceRun(page);
  assert.deepEqual(run.end, stepped.at(-1), 'Run ends where stepping ends');
  assert.deepEqual(run.trace, stepped.slice(1), 'Run draws exactly the states stepping draws');
  await setControl(page, S.seed, 17011);
  assert.equal(+(await page.locator('#planner').getAttribute('data-seed')), 17011, 'the planner uses the chosen seed');
  assert.notDeepEqual((await scene(page)).views, start.views, 'another seed plans another path');
});

test('reduced motion: Run is unavailable and Step works; switching to reduced motion stops a Run', async t => {
  const page = await pageFor(t, { reducedMotion: 'reduce' });
  const run = page.locator(S.run), unavailable = async () => !(await run.isVisible()) || !(await run.isEnabled());
  assert.ok(await unavailable(), 'Run unavailable under reduced motion');
  await page.locator(S.step).click();
  assert.equal((await time(page)).k, 1, 'Step advances by one');
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await eventually(async () => { assert.equal(await run.isVisible(), true); assert.equal(await run.isEnabled(), true); });
  await run.click();
  await waitRunning(page);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await eventually(async () => assert.ok(await unavailable()));
  const stopped = await scene(page);
  await page.waitForTimeout(400); // over three animation steps
  assert.deepEqual(await scene(page), stopped, 'the media change stops the Run');
});

test('changing the error or the mass during a Run cancels it and restarts at Step 0', async t => {
  const page = await pageFor(t);
  const error = await limits(page, S.error), mass = await limits(page, S.mass);
  for (const [selector, value] of [[S.error, error.max], [S.mass, mass.max]]) {
    await page.locator(S.run).click();
    await waitRunning(page);
    await setControl(page, selector, value);
    const reset = await scene(page);
    await page.waitForTimeout(350); // over two animation steps
    assert.deepEqual(await scene(page), reset, 'a cancelled Run never resumes');
  }
});

// ---- Panel 2: a frozen Fourier fit of two orbits, broken by an added mass. ----

function orbitConfig(config) {
  const o = pick(config, 'orbit', 'orbits', 'kepler');
  assert.ok(o, 'expose orbit configuration');
  const out = { ...o, centralPosition: pick(o, 'centralPosition', 'center'),
    addedPosition: pick(o, 'addedPosition', 'massPosition'),
    initialStates: pick(o, 'initialStates', 'initialConditions'), times: pick(o, 'times', 'sampleTimes'),
    trainEnd: pick(o, 'trainEnd', 'trainingEnd'), harmonics: pick(o, 'harmonics', 'order') };
  for (const key of ['dt', 'G', 'centralMass', 'softening', 'trainEnd']) assert.ok(Number.isFinite(out[key]) && out[key] > 0, `positive orbit ${key}`);
  assert.equal(out.initialStates.length, 2, 'two test particles');
  assert.ok(Number.isInteger(out.harmonics) && out.harmonics > 0 && out.harmonics <= 20, 'bounded truncated Fourier order');
  assert.ok(out.times.length > 20 && out.times.some(t => t > out.trainEnd), 'sampled training and held-out horizon');
  out.times.forEach((t, i) => {
    assert.ok(Number.isFinite(t) && t >= 0 && (!i || t > out.times[i - 1]), 'strict sample times');
    near(t / out.dt, Math.round(t / out.dt), 1e-7, 'fixed-step sample grid');
  });
  return out;
}
// Independent softened Newtonian velocity-Verlet. The moving particles never attract each other;
// the central and added attractors stay fixed.
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
    vector(pick(series, 'times', 'sampleTimes') ?? c.times, c.times, 1e-8, 'identical orbit sample times');
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
// fitOrbit returns {period, coefficients: [x, y]}, each [constant, cos 1, sin 1, ..., cos h, sin h].
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
// Extent = largest baseline x/y span. The held-out error uses the same normaliser for every mass.
function extent(trajectory) {
  return Math.max(...[0, 1].map(j => Math.max(...trajectory.map(p => p[j])) - Math.min(...trajectory.map(p => p[j]))));
}
function orbitError(truth, predicted, baseline, c) {
  return truth.map((trajectory, j) => Math.max(...trajectory.flatMap((p, i) => c.times[i] > c.trainEnd ? [distance(p, predicted[j][i])] : [])) / extent(baseline[j]));
}
async function orbitScene(page) {
  const get = selector => page.locator(`#kepler ${selector}`).evaluateAll(els => els.map(el => Array.from(el.points, p => [p.x, p.y])));
  return { truth: await get('polyline[data-kepler-true]'), predicted: await get('polyline[data-kepler-predicted]'),
    error: (await page.locator('[data-kepler-error]').innerText()).trim() };
}
function errorReadout(text, errors) {
  // The displayed number is the worst held-out error as a fraction or percentage of orbit extent.
  const matches = [...text.matchAll(/(\d+(?:\.\d+)?(?:e[-+]?\d+)?)\s*(%|fraction|×|x\b)?/gi)];
  const expected = Math.max(...errors);
  assert.ok(matches.some(m => {
    const value = Number(m[1]) / (m[2] === '%' ? 100 : 1);
    const decimals = m[1].split(/[eE]/)[0].split('.')[1]?.length ?? 0;
    const exponent = Number(m[1].split(/[eE]/)[1] ?? 0);
    const rounding = 0.5 * 10 ** (exponent - decimals) / (m[2] === '%' ? 100 : 1) + 1e-8;
    // A coarse 0 or 1 label does not count as a quantitative error.
    return rounding <= 0.0051 && Math.abs(expected - value) <= rounding;
  }), `error readout must match the independently measured fraction: ${text}, expected ${expected}`);
}

test('orbit fitter estimates an unseen period and Fourier coefficients from synthetic samples', async t => {
  const page = await pageFor(t), c = orbitConfig(await api(page, 'config'));
  const random = rng(1259), period = 3.2 + 4 * random();
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
  vector(fit.coefficients, fitFourierAtPeriod(samples, fit), 1e-6, 'least-squares coefficients at that period');
  vector(fit.coefficients, coeffs, 0.04, 'known Fourier coefficients recovered');
  const future = [period * 4.1, period * 4.33, period * 4.89];
  const actual = points(await api(page, 'predictOrbit', [raw, future]));
  vector(actual, evaluateFourier(fit, future), 1e-6, 'predictor implements the Fourier sum');
  vector(actual, evaluateFourier(truthFit, future), 0.05, 'held-out synthetic orbit recovered');
});

test('orbits: Verlet physics, frozen fit, held-out error readout, the mass slider and Reset', async t => {
  const page = await pageFor(t), c = orbitConfig(await api(page, 'config')), mass = await limits(page, S.mass);
  assert.equal(mass.min, 0); assert.equal(mass.default, 0); assert.ok(mass.max > 0);
  const baseline = orbitOracle(c, 0), predicted = [];
  for (const trajectory of baseline) {
    const samples = samplesAt(c.times, trajectory, t => t <= c.trainEnd);
    assert.ok(samples.length > 2 * c.harmonics + 1, 'overdetermined training fit');
    const raw = await api(page, 'fitOrbit', [samples]), fit = orbitFitView(raw);
    assert.equal(fit.harmonics, c.harmonics, 'page exposes fitted harmonic count');
    vector(fit.coefficients, fitFourierAtPeriod(samples, fit), 2e-6, 'independent baseline least squares');
    const prediction = points(await api(page, 'predictOrbit', [raw, c.times]));
    vector(prediction, evaluateFourier(fit, c.times), 2e-6, 'Fourier predictions from coefficients');
    predicted.push(prediction);
  }
  const baseErrors = orbitError(baseline, predicted, baseline, c);
  baseErrors.forEach(e => assert.ok(e < 0.02, `mass-0 held-out error ${e} < 2% of orbit extent`));
  let baselineDraw, planner;
  for (const m of [0, mass.max]) {
    const truth = orbitOracle(c, m), errors = orbitError(truth, predicted, baseline, c);
    vector(orbitSeries(await api(page, 'simulateOrbits', [m]), c), truth, 2e-6, 'independent velocity-Verlet physics');
    await setControl(page, S.mass, m);
    const drawn = await orbitScene(page);
    vector(drawn.truth, truth, 2e-4, 'true orbital SVG');
    vector(drawn.predicted, predicted, 2e-4, 'frozen fitted orbital SVG');
    errorReadout(drawn.error, errors);
    if (m === 0) { baselineDraw = drawn; planner = (await scene(page)).views; continue; }
    errors.forEach((e, j) => {
      assert.ok(e > 0.10, `added-mass error ${e} > 10%`);
      assert.ok(e >= 10 * baseErrors[j], 'added mass breaks the frozen predictor by >= 10x');
    });
    assert.notEqual(drawn.error, baselineDraw.error, 'the error readout changes, not only the paths');
    assert.deepEqual((await scene(page)).views, planner, 'orbital mass does not change the point-mass world');
  }
  await page.locator(S.reset).click();
  await eventually(async () => assert.equal(+(await page.locator(S.mass).inputValue()), 0), 'Reset restores mass 0');
  vector((await orbitScene(page)).truth, baseline, 2e-4, 'Reset restores baseline physics');
});
