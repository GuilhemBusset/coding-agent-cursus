import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from './browser.mjs';

test('D7: the deck planner recipe reaches the goal with feedback in the actual offline lab', async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ reducedMotion: 'reduce' });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route(/^https?:/, route => { errors.push(route.request().url()); return route.abort(); });
    await page.goto(pathToFileURL(path.resolve('sessions/01-fundamentals/cursus/02-thinking.html')).href + '#repo-model');
    const recipe = await page.locator('#repo-model .recipe').evaluate(dl => Object.fromEntries([...dl.querySelectorAll('div')].map(row => [row.querySelector('dt').textContent.trim(), row.querySelector('dd').textContent.trim()])));
    assert.ok(Number.isFinite(Number(recipe.Seed)));
    assert.ok(Number.isFinite(Number(recipe['Model error'])));
    await page.locator('#repo-model a[href*="world-model"]').click();
    assert.equal(new URL(page.url()).hash, '#planner');
    await page.locator('[data-wm-seed]').fill(recipe.Seed);
    await page.locator('[data-wm-seed]').dispatchEvent('change');
    await page.locator('[data-wm-error]').evaluate((input, value) => { input.value = value; input.dispatchEvent(new Event('input', { bubbles: true })); }, recipe['Model error']);
    await page.locator('[data-wm-reset]').click();
    for (let i = 0; i < 30 && await page.locator('[data-wm-step]').isEnabled(); i++) await page.locator('[data-wm-step]').click();
    const views = await page.locator('[data-wm-view]').evaluateAll(nodes => nodes.map(node => {
      const circle = selector => { const c = node.querySelector(selector); return { x: +c.getAttribute('cx'), y: +c.getAttribute('cy'), r: +c.getAttribute('r') }; };
      return { mode: node.dataset.wmView, outcome: node.dataset.outcome, point: circle('[data-wm-agent]'), goal: circle('[data-wm-goal]') };
    }));
    const closed = views.find(v => v.mode === 'closed');
    const open = views.find(v => v.mode === 'open');
    assert.equal(open.outcome, 'hit obstacle');
    assert.equal(closed.outcome, 'reached goal');
    assert.ok(Math.hypot(closed.point.x - closed.goal.x, closed.point.y - closed.goal.y) <= closed.goal.r + 0.00002, 'displayed goal success agrees with final geometry');
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});
