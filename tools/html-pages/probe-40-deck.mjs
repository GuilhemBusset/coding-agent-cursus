import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from './browser.mjs';

test('D1: offline deck navigation exposes usable speaker notes on every slide', async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route(/^https?:/, route => { errors.push(route.request().url()); return route.abort(); });
    await page.goto(pathToFileURL(path.resolve('sessions/01-fundamentals/cursus/02-thinking.html')).href);
    assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'deck');
    const ids = await page.locator('[data-slide]').evaluateAll(slides => slides.map(s => s.id));
    assert.ok(ids.length > 1);
    for (let i = 0; i < ids.length; i++) {
      const slide = page.locator('[data-slide]:visible');
      assert.equal(await slide.count(), 1);
      assert.equal(await slide.getAttribute('id'), ids[i]);
      const notes = slide.locator('details.notes');
      assert.equal(await notes.count(), 1);
      await notes.locator('summary').click();
      assert.equal(await notes.getAttribute('open'), '');
      assert.ok((await notes.locator('p').allTextContents()).join(' ').trim().length > 40);
      assert.ok(await notes.locator('p').first().isVisible());
      await notes.locator('summary').press('Enter');
      assert.equal(await notes.getAttribute('open'), null);
      if (i < ids.length - 1) await page.locator('[data-next]').click();
    }
    assert.ok(await page.locator('[data-next]').isDisabled());
    await page.locator('[data-slide]:visible').focus();
    await page.keyboard.press('Home');
    assert.equal(await page.locator('[data-slide]:visible').getAttribute('id'), ids[0]);
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});
