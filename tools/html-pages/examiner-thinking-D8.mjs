import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { chromium } from './browser.mjs';

const session = path.resolve('sessions/01-fundamentals');
const deck = path.join(session, 'cursus/02-thinking.html');
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, reducedMotion: 'reduce' });
const errors = [], requests = [];
await context.route(/^https?:/, route => { requests.push(route.request().url()); return route.abort(); });
const page = await context.newPage();
page.on('pageerror', error => errors.push(String(error)));
try {
  await page.goto(pathToFileURL(deck).href);
  const ids = await page.locator('[data-slide]').evaluateAll(slides => slides.map(s => s.id));
  assert.ok(ids.length > 1);
    for (const [id, suffix] of [['search', '#best-of-n'], ['sharpen-or-expand', '#sharpen-or-expand'], ['overthinking', '#effort-dial'], ['kepler', '#kepler'], ['repo-model', '#planner'], ['effort-demo', 'README.md']]) {
      await page.goto(`${pathToFileURL(deck).href}#${id}`);
      const link = page.locator(`#${id} a`).filter({ hasText: suffix === 'README.md' ? 'README' : /Test-time compute|World model/ });
      assert.equal(await link.count(), 1);
      const target = new URL(await link.getAttribute('href'), page.url());
      assert.equal(target.protocol, 'file:');
      assert.ok(fileURLToPath(target).startsWith(session + path.sep));
      assert.ok((await readFile(fileURLToPath(target))).length > 0);
      assert.ok(target.href.endsWith(suffix));
      if (target.hash) {
        await link.click();
        await page.waitForURL(target.href);
        assert.ok(await page.locator(target.hash).isVisible());
      }
    }
    await page.goto(`${pathToFileURL(deck).href}#effort-demo`);
    assert.equal(await page.locator('#effort-demo table:visible').count(), 0);
    await page.locator('#effort-demo .reveal summary').click();
    assert.equal(await page.locator('#effort-demo table:visible').count(), 1);
    const rows = await page.locator('#effort-demo tbody tr').allTextContents();
    const recorded = JSON.parse(await readFile(path.join(session, 'cursus/demos/effort/recorded/results.json'), 'utf8'));
    assert.equal(rows.length, recorded.runs.length);
    for (let i = 0; i < rows.length; i++) {
      const run = recorded.runs[i];
      for (const value of [run.model, run.effort, run.tokens.output, run.cost_usd.toFixed(4), run.answer]) assert.ok(rows[i].includes(String(value)), `${run.model}: ${value}`);
    }
  assert.deepEqual(errors, []);
  assert.deepEqual(requests, [], 'no network required');
  console.log("PASS");
} finally { await browser.close(); }
