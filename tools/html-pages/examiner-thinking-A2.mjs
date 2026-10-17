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
    const minutes = await page.locator('[data-slide] details.notes').evaluateAll(notes => notes.map(n => Number(n.dataset.minutes)));
    assert.equal(minutes.length, ids.length);
    assert.ok(minutes.every(n => Number.isFinite(n) && n > 0));
    assert.equal(minutes.reduce((a, b) => a + b, 0), 45);
    const schedule = await readFile(path.join(session, 'cursus/02-thinking/rehearsal.md'), 'utf8');
    assert.match(schedule, /Observed minutes/);
    for (const viewport of [{width: 1440, height: 900}, {width: 1280, height: 720}, {width: 390, height: 844}]) {
      await page.setViewportSize(viewport);
      for (const id of ids) {
        await page.goto(`${pathToFileURL(deck).href}#${id}`);
        assert.ok(await page.locator(`#${id}`).isVisible());
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${id}: document fits`);
        if (viewport.width >= 800) {
          assert.ok(await page.locator(`#${id}`).evaluate(el => el.scrollHeight <= el.clientHeight + 1), `${id}: slide fits without scrolling`);
        }
      }
      await page.goto(`${pathToFileURL(deck).href}#effort-demo`);
      await page.locator('#effort-demo .reveal summary').click();
      if (viewport.width >= 800) assert.ok(await page.locator('#effort-demo').evaluate(el => el.scrollHeight <= el.clientHeight + 1), 'revealed results fit');
    }
    await page.emulateMedia({ media: 'print' });
    assert.equal(await page.locator('[data-slide]:visible').count(), ids.length);
  assert.deepEqual(errors, []);
  assert.deepEqual(requests, [], 'no network required');
  console.log("PASS");
} finally { await browser.close(); }
