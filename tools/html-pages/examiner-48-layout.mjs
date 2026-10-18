import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import { chromium } from './browser.mjs';

const browser = await chromium.launch();
try {
  for (const viewport of [{ width: 1280, height: 720 }, { width: 1440, height: 900 }]) {
    const context = await browser.newContext({ offline: true, viewport });
    const page = await context.newPage();
    await page.goto(pathToFileURL(path.resolve('sessions/01-fundamentals/cursus/03-agent.html')).href);
    const ids = await page.locator('[data-slide]').evaluateAll(nodes => nodes.map(n => n.id));
    for (const id of ids) {
      await page.evaluate(id => { location.hash = id; }, id);
      await page.waitForFunction(id => document.querySelector('[data-slide]:not([hidden])')?.id === id, id);
      const slide = page.locator('#' + id);
      const fits = () => slide.evaluate(s => ({ x: s.scrollWidth - s.clientWidth, y: s.scrollHeight - s.clientHeight }));
      let size = await fits();
      assert.ok(size.x <= 2 && size.y <= 2, `${id} at ${viewport.width}: ${JSON.stringify(size)}`);
      const reveal = slide.locator('details.reveal');
      if (await reveal.count()) {
        await reveal.locator('summary').click();
        size = await fits();
        assert.ok(size.x <= 2 && size.y <= 2, `${id} revealed at ${viewport.width}: ${JSON.stringify(size)}`);
        await reveal.locator('summary').click();
      }
    }
    await context.close();
  }
  console.log('PASS: all slides and demo reveals fit laptop and desktop viewports');
} finally { await browser.close(); }
