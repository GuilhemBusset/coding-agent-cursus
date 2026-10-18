import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
import {chromium} from './browser.mjs';

const deck = pathToFileURL(path.resolve('sessions/01-fundamentals/cursus/03-agent.html')).href;
const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  await page.route(/^https?:/, route => route.abort());
  await page.goto(deck);
  const links = await page.locator('[data-slide] a[href^="labs/"]').evaluateAll(nodes => nodes.map(n => n.href));
  assert.ok(links.some(h => h.includes('context.html')));
  assert.ok(links.some(h => h.includes('agent-loop.html')));
  for (const href of new Set(links)) {
    await page.goto(href);
    const target = new URL(href);
    if (target.hash.startsWith('#run=')) {
      const id = decodeURIComponent(target.hash.slice(5));
      assert.equal(await page.locator('#run-select').inputValue(), id, href);
      assert.ok(await page.locator('[data-stepper]:visible').count() > 0, href);
    } else if (target.hash) {
      assert.ok(await page.locator(target.hash).isVisible(), href);
    } else {
      assert.ok(await page.locator('main').isVisible(), href);
    }
  }
  console.log('PASS: deck lab links open offline; every replay selects the named recording');
} finally { await browser.close(); }
