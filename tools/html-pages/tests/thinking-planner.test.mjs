import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
import { repoRoot, read, openPage, assertCollected } from './component-helpers.mjs';

// Issue 40 amendment: execute the recipe the instructor actually reads. The
// recipe is ordinary rendered text, including the opened speaker notes; no
// test-only attributes or baked-in recipe values are required in the deck.
// WorldModel's public run records/config and the lab's existing view/outcome
// attributes are the interchange contract established by world-model.test.mjs.
const deck = path.join(repoRoot, 'sessions/01-fundamentals/cursus/02-thinking.html');
const lab = path.join(repoRoot, 'sessions/01-fundamentals/cursus/labs/world-model.html');
const promised = { open: 'Hit obstacle', closed: 'Reached goal' };

function parseRecipe(text) {
  const seeds = [...text.matchAll(/\bseed\b\s*[:=]?\s*(\d+)\b(?!\.\d)/gi)];
  const errors = [...text.matchAll(/\bmodel[\s-]+error\b\s*[:=]?\s*(\d+\.\d+)\b/gi)];
  assert.equal(seeds.length, 1, 'repo-model must communicate exactly one integer near Seed');
  assert.equal(errors.length, 1, 'repo-model must communicate exactly one decimal near Model error');
  const seed = Number(seeds[0][1]), error = Number(errors[0][1]);
  assert.ok(Number.isSafeInteger(seed) && seed >= 0 && seed <= 4294967295, 'valid unsigned seed');
  assert.ok(Number.isFinite(error) && error >= 0 && error <= 1, 'model error between zero and one');
  return { seed, error };
}

async function deckActivity(t, reducedMotion = 'no-preference') {
  const page = await openPage(t, chromium, { file: deck, reducedMotion });
  await page.goto(`${pathToFileURL(deck).href}#repo-model`);
  const slide = page.locator('#repo-model');
  assert.equal(await slide.count(), 1, 'one repo-model slide');
  assert.equal(await slide.isVisible(), true, 'the linked slide is rendered');
  const notes = slide.locator('details').filter({ has: page.locator('summary', { hasText: /speaker notes/i }) });
  assert.equal(await notes.count(), 1, 'readable speaker notes');
  if (!(await notes.evaluate(el => el.open))) await notes.locator('summary').click();
  const text = await slide.innerText(), spoken = await notes.innerText();
  const recipe = parseRecipe(text);
  assert.match(spoken, /\bReset\b/i, 'recipe tells the instructor to Reset');
  assert.match(spoken, /\bRun\b/i, 'recipe tells the instructor to Run');
  assert.match(spoken, /reduced[\s-]+motion/i, 'recipe covers reduced motion');
  assert.match(spoken, /\bStep\b/i, 'reduced-motion recipe uses Step');
  // Check the promised terminal events without prescribing an entire sentence.
  assert.match(spoken, /open[\s-]+loop\b[^.!?]*\bhits?\b[^.!?]*\bobstacle\b/i,
    'notes say the open loop hits the obstacle');
  assert.match(spoken, /closed[\s-]+loop\b[^.!?]*\breaches?\b[^.!?]*\bgoal\b/i,
    'notes say the closed loop reaches the goal');
  const links = slide.locator('a[href]');
  const plannerLinks = [];
  for (const link of await links.all()) {
    const href = await link.getAttribute('href');
    if (new URL(href, page.url()).hash === '#planner') plannerLinks.push(link);
  }
  assert.equal(plannerLinks.length, 1, 'one actual planner activity link');
  const link = plannerLinks[0];
  const target = new URL(await link.getAttribute('href'), page.url());
  assert.equal(target.protocol, 'file:', 'planner opens offline');
  assert.equal(target.search, '', 'no query-dependent planner fixture');
  assert.equal(path.resolve(fileURLToPath(target)), lab, 'planner resolves inside this session to world-model.html');
  await link.click();
  await page.waitForURL(target.href);
  assert.equal(new URL(page.url()).hash, '#planner');
  assert.equal(await page.locator('#planner').isVisible(), true, 'deep link lands on the rendered planner panel');
  await page.waitForFunction(() => window.WorldModel &&
    typeof window.WorldModel.runOpenLoop === 'function' && typeof window.WorldModel.runClosedLoop === 'function');
  return { page, recipe };
}

async function settings(page, { seed, error }) {
  const panel = page.locator('#planner');
  const seedInput = panel.getByLabel(/^Seed$/i, { exact: true });
  const errorInput = panel.getByLabel(/^Model error$/i, { exact: true });
  assert.equal(await seedInput.getAttribute('type'), 'number', 'native seed control');
  assert.equal(await errorInput.getAttribute('type'), 'range', 'native error control');
  await seedInput.fill(String(seed));
  await seedInput.dispatchEvent('change');
  await errorInput.evaluate((el, value) => {
    el.value = String(value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }, error);
  assert.equal(Number(await seedInput.inputValue()), seed, 'seed is accepted without clamping');
  assert.equal(Number(await errorInput.inputValue()), error, 'model error is accepted without clamping');
}

async function outcomes(page) {
  const result = {};
  for (const kind of ['open', 'closed']) {
    const label = page.locator(`#planner [data-wm-view="${kind}"] [data-wm-outcome]`);
    assert.equal(await label.count(), 1, `one ${kind} outcome`);
    assert.equal(await label.isVisible(), true, `${kind} outcome is visible`);
    result[kind] = (await label.innerText()).trim();
  }
  return result;
}

async function reset(page) {
  await page.locator('#planner').getByRole('button', { name: 'Reset', exact: true }).click();
  assert.deepEqual(await outcomes(page), { open: 'Running', closed: 'Running' }, 'Reset starts both trajectories again');
}

async function finish(page, stepMode = false) {
  const panel = page.locator('#planner');
  if (stepMode) {
    // Bound the manual replay by the public horizon, rather than a lucky number
    // of clicks. A failed or nonadvancing Step must fail rather than hang/skip.
    const horizon = await page.evaluate(() => window.WorldModel.config.world.steps);
    assert.ok(Number.isInteger(horizon) && horizon > 0 && horizon <= 10000, 'finite execution horizon');
    for (let k = 0; k < horizon; k++) {
      if (Object.values(await outcomes(page)).every(v => v !== 'Running')) break;
      await panel.getByRole('button', { name: 'Step', exact: true }).click();
    }
    assert.ok(Object.values(await outcomes(page)).every(v => v !== 'Running'), 'Step finishes both views');
  } else {
    await panel.getByRole('button', { name: 'Run', exact: true }).click();
    await page.waitForFunction(() => {
      const views = document.querySelectorAll('#planner [data-wm-outcome]');
      return views.length === 2 && [...views].every(el => el.textContent.trim() !== 'Running');
    }, null, { timeout: 15000 });
  }
  return outcomes(page);
}

const point = value => {
  const p = Array.isArray(value) || ArrayBuffer.isView(value) ? [value[0], value[1]] : [value?.x, value?.y];
  assert.ok(p.every(Number.isFinite), 'finite trajectory/geometry coordinates');
  return p;
};
function circle(value) {
  assert.ok(value, 'world exposes circle geometry');
  const radius = value.radius ?? value.r;
  assert.ok(Number.isFinite(radius) && radius > 0, 'positive finite circle radius');
  return { center: point(value.center ?? value.position ?? value), radius };
}
function intersects(a, b, obstacle) {
  const dx = b[0] - a[0], dy = b[1] - a[1], squared = dx * dx + dy * dy;
  const t = squared === 0 ? 0 : Math.max(0, Math.min(1,
    ((obstacle.center[0] - a[0]) * dx + (obstacle.center[1] - a[1]) * dy) / squared));
  return Math.hypot(a[0] + t * dx - obstacle.center[0], a[1] + t * dy - obstacle.center[1]) <= obstacle.radius;
}
function geometricOutcome(points, world) {
  assert.ok(points.length >= 2, 'executed trajectory, not a terminal-label stub');
  const path = points.map(point), obstacle = circle(world.obstacle), goal = circle(world.goal);
  if (path.slice(1).some((p, i) => intersects(path[i], p, obstacle))) return 'Hit obstacle';
  const final = path.at(-1);
  return Math.hypot(final[0] - goal.center[0], final[1] - goal.center[1]) <= goal.radius ? 'Reached goal' : 'Missed goal';
}

async function audit(page, recipe, rendered) {
  // Call the independent public numerical runs, not UI state or its cached
  // terminal labels. Copy only executed positions (plans can be very large).
  const data = await page.evaluate(({ seed, error }) => {
    const W = window.WorldModel;
    const runs = {};
    for (const [kind, method] of [['open', 'runOpenLoop'], ['closed', 'runClosedLoop']]) {
      const run = W[method](seed, error), records = Array.isArray(run) ? run : run.records;
      if (!Array.isArray(records) || records.length === 0) throw new Error(`${method} must return executed step records`);
      const xy = state => [state[0], state[1]];
      runs[kind] = { outcome: run.outcome, segments: records.map(r => [xy(r.state), xy(r.nextState)]) };
    }
    return { world: W.config.world, runs };
  }, recipe);
  const paths = {};
  for (const kind of ['open', 'closed']) {
    const run = data.runs[kind], points = [point(run.segments[0][0])];
    for (const [from, to] of run.segments) {
      const prior = points.at(-1), start = point(from);
      assert.ok(Math.hypot(prior[0] - start[0], prior[1] - start[1]) < 1e-8, 'continuous executed trajectory');
      points.push(point(to));
    }
    assert.deepEqual(points[0], point(data.world.start), 'trajectory starts at the configured start');
    const calculated = geometricOutcome(points, data.world);
    assert.equal(rendered[kind], calculated, `${kind}: rendered outcome matches independently computed geometry`);
    if (run.outcome !== undefined) assert.equal(run.outcome.toLowerCase(), calculated.toLowerCase(), `${kind}: API outcome agrees with geometry`);
    paths[kind] = points;
  }
  return { outcomes: rendered, paths };
}

async function demonstrate(page, recipe, stepMode = false) {
  await settings(page, recipe);
  await reset(page);
  const rendered = await finish(page, stepMode);
  assert.deepEqual(rendered, promised, 'deck recipe produces both promised outcomes');
  return audit(page, recipe, rendered);
}

test('npm --prefix setup test collects the thinking and thinking-planner suites', async () => {
  assert.ok((await read('tools/html-pages/tests/thinking.test.mjs')).trim().length, 'the thinking suite is nonempty');
  await assertCollected('thinking');
  await assertCollected('thinking-planner');
});

test('recipe parser accepts ordinary labels and rejects absent or ambiguous settings', () => {
  assert.deepEqual(parseRecipe('Seed\n17011\nModel error\n0.35\nReset, Run'), { seed: 17011, error: 0.35 });
  assert.deepEqual(parseRecipe('Seed: 92821; Model error = 1.00'), { seed: 92821, error: 1 });
  for (const text of ['Reset then Run', 'Seed 17; Model error 0.5; Seed 18',
    'Seed 17; Model error 0.5; Model error 0.9', 'Seed 17.5; Model error 0.5']) {
    assert.throws(() => parseRecipe(text), assert.AssertionError, text);
  }
});

test('geometry oracle catches crossed obstacles, tangency, stationary points and terminal goal membership', () => {
  const world = { obstacle: { center: [0, 0], radius: 1 }, goal: { center: [4, 0], radius: 0.5 } };
  assert.equal(geometricOutcome([[-2, 0], [4, 0]], world), 'Hit obstacle', 'endpoints outside obstacle still intersect');
  assert.equal(geometricOutcome([[-2, 1], [2, 1]], world), 'Hit obstacle', 'tangent contact is collision');
  assert.equal(geometricOutcome([[0, 0], [0, 0]], world), 'Hit obstacle');
  assert.equal(geometricOutcome([[4, 0], [4.5, 0]], world), 'Reached goal', 'goal radius is inclusive');
  assert.equal(geometricOutcome([[4, 0], [5, 0]], world), 'Missed goal', 'the final point matters');
});

test('D8: actual deck planner href opens the offline planner panel', async t => {
  await deckActivity(t);
});

test('D7: recipe on a fresh lab gives the promised geometric outcomes', { timeout: 30000 }, async t => {
  const { page, recipe } = await deckActivity(t);
  await demonstrate(page, recipe);
});

test('D7: recipe recovers after a different seed and maximum-error run', { timeout: 45000 }, async t => {
  const { page, recipe } = await deckActivity(t);
  const dirty = { seed: 92821, error: 1.00 };
  await settings(page, dirty);
  await reset(page);
  const before = await audit(page, dirty, await finish(page));
  const after = await demonstrate(page, recipe);
  assert.notDeepEqual(before.paths, after.paths, 'recipe replaces the prior run, rather than replaying cached trajectories');
  assert.notDeepEqual(before.outcomes, after.outcomes, 'alternate case rules out constant success labels');
});

test('D7: Reset and replay produce identical trajectories and outcomes twice in a row', { timeout: 45000 }, async t => {
  const { page, recipe } = await deckActivity(t);
  const first = await demonstrate(page, recipe);
  await reset(page);
  const rendered = await finish(page);
  assert.deepEqual(rendered, promised);
  assert.deepEqual(await audit(page, recipe, rendered), first, 'Reset preserves recipe and deterministically replays it');
});

test('D7: under reduced motion the recipe finishes through native Step controls', { timeout: 30000 }, async t => {
  const { page, recipe } = await deckActivity(t, 'reduce');
  await demonstrate(page, recipe, true);
});
