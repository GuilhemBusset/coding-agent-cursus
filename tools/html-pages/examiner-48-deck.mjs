import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from './browser.mjs';
const browser = await chromium.launch();
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, offline: true });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(pathToFileURL(path.resolve('sessions/01-fundamentals/cursus/03-agent.html')).href);
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'deck');
  const slides = page.locator('[data-slide]');
  const count = await slides.count();
  assert.ok(count > 1);
  const ids = await slides.evaluateAll(nodes => nodes.map(node => node.id));
  assert.equal(new Set(ids).size, count);
  for (let i = 0; i < count; i++) {
    await page.waitForFunction(id => {
      const shown = [...document.querySelectorAll('[data-slide]')].filter(node => getComputedStyle(node).display !== 'none');
      return shown.length === 1 && shown[0].id === id;
    }, ids[i]);
    assert.equal(await page.locator('[data-slide-status]').textContent(), `Slide ${i + 1} of ${count}`);
    if (i < count - 1) await page.locator('[data-next]').click();
  }
  assert.equal(await page.locator('[data-next]').isDisabled(), true);
  await slides.last().focus();
  await page.keyboard.press('Home');
  await page.waitForFunction(id => !document.getElementById(id).hidden, ids[0]);
  assert.equal(await page.locator('[data-prev]').isDisabled(), true);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(() => [...document.querySelectorAll('[data-slide]')].every(node => getComputedStyle(node).display !== 'none'));
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  assert.deepEqual(errors, []);
  const noJS = await browser.newContext({ javaScriptEnabled: false, offline: true });
  const reader = await noJS.newPage();
  await reader.goto(page.url().split('#')[0]);
  assert.equal(await reader.locator('[data-slide]:visible').count(), count);
  console.log(`PASS D1: ${count} slides, pointer/keyboard navigation, mobile and no-JS reading.`);
} finally { await browser.close(); }
