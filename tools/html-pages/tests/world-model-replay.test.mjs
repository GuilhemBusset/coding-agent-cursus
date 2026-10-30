// Moved from world-model.test.mjs unchanged: the lab's longest test (about 75 s locally, 130 s
// on CI) gets its own suite file, so node --test runs it beside the rest of that suite.
import test from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from '../browser.mjs'; // the pinned browser that pageFor launches
import { eventually } from './component-helpers.mjs';
import {
  S, api, limits, pageFor, rangeAt, scene, setControl, stepToEnd,
  traceRun,
} from './world-model-helpers.mjs';

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
