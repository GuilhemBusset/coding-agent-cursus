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
    for (const id of ids) {
      await page.goto(`${pathToFileURL(deck).href}#${id}`);
      const slide = page.locator(`[data-slide][id="${id}"]`);
      assert.ok(await slide.isVisible(), id);
      const notes = slide.locator('details.notes');
      assert.equal(await notes.count(), 1);
      await notes.locator('summary').click();
      assert.ok((await notes.innerText()).length > 80, `${id}: meaningful notes`);
      await notes.locator('summary').click();
    }
    await page.goto(pathToFileURL(deck).href);
    await page.locator('[data-next]').click();
    assert.equal(new URL(page.url()).hash, `#${ids[1]}`);
    await page.goBack();
    assert.ok(await page.locator(`#${ids[0]}`).isVisible());
    const plain = await browser.newContext({ javaScriptEnabled: false });
    const p = await plain.newPage();
    await p.goto(pathToFileURL(deck).href);
    assert.equal(await p.locator('[data-slide]:visible').count(), ids.length);
    await plain.close();
  assert.deepEqual(errors, []);
  assert.deepEqual(requests, [], 'no network required');
  console.log("PASS");
} finally { await browser.close(); }
