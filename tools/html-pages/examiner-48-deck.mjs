import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import { chromium } from './browser.mjs';

const browser = await chromium.launch();
try {
  const context = await browser.newContext({ offline: true, viewport: { width: 1280, height: 720 } });
  const page = await context.newPage();
  await page.goto(pathToFileURL(path.resolve('sessions/01-fundamentals/cursus/03-agent.html')).href);
  assert.equal(await page.locator('html').getAttribute('data-page-kind'), 'deck');
  const ids = await page.locator('[data-slide]').evaluateAll(nodes => nodes.map(n => n.id));
  assert.ok(ids.length > 1);
  const visible = () => page.locator('[data-slide]:visible').evaluateAll(nodes => nodes.map(n => n.id));
  assert.deepEqual(await visible(), [ids[0]]);
  await page.locator('[data-next]').click();
  assert.deepEqual(await visible(), [ids[1]]);
  assert.equal(new URL(page.url()).hash, '#' + ids[1]);
  await page.locator('body').click({ position: { x: 5, y: 5 } });
  await page.keyboard.press('End');
  assert.deepEqual(await visible(), [ids.at(-1)]);
  await page.keyboard.press('Home');
  assert.deepEqual(await visible(), [ids[0]]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(n => [...document.querySelectorAll('[data-slide]')].filter(s => s.getBoundingClientRect().height > 0).length === n, ids.length);
  assert.equal(await page.locator('[data-slide]:visible').count(), ids.length);
  await context.close();
  const noJS = await browser.newContext({ offline: true, javaScriptEnabled: false });
  const plain = await noJS.newPage();
  await plain.goto(pathToFileURL(path.resolve('sessions/01-fundamentals/cursus/03-agent.html')).href);
  assert.equal(await plain.locator('[data-slide]:visible').count(), ids.length);
  console.log('PASS: offline deck navigation, responsive reading and no-JS reading');
} finally { await browser.close(); }
