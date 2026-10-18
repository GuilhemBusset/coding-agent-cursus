import assert from 'node:assert/strict';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from './browser.mjs';
const browser = await chromium.launch();
try {
  const context = await browser.newContext({ offline: true });
  const page = await context.newPage();
  const root = path.resolve('sessions/01-fundamentals');
  const deck = pathToFileURL(path.join(root, 'cursus/03-agent.html')).href;
  await page.goto(deck);
  const links = await page.locator('[data-slide] a[href]').evaluateAll(nodes => nodes.map(node => ({ href: node.href, slide: node.closest('[data-slide]').id })));
  for (const slide of ['loop-demo', 'bomb-demo']) {
    assert.ok(links.some(link => link.slide === slide && link.href.includes('/demos/agent/') && link.href.endsWith('.md')), `${slide}: runbook`);
    assert.ok(links.some(link => link.slide === slide && link.href.includes('/labs/agent-loop.html#run=')), `${slide}: replay`);
  }
  assert.ok(links.some(link => link.href.includes('/labs/context.html')));
  let runs = 0;
  for (const href of new Set(links.map(link => link.href).filter(href => href.startsWith('file:')))) {
    const url = new URL(href);
    const target = fileURLToPath(url);
    const relative = path.relative(root, target);
    assert.ok(relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative), href);
    assert.ok((await stat(target)).isFile(), href);
    if (url.hash.startsWith('#run=')) {
      await page.goto(href);
      const id = decodeURIComponent(url.hash.slice(5));
      assert.equal(await page.locator('#run-select').inputValue(), id, href);
      const label = await page.locator('[data-fact="id"]').textContent();
      assert.ok(label === id || label.startsWith(`${id} (`), href);
      assert.ok(await page.locator('[data-runs] [data-step]').count() > 0, href);
      runs++;
    } else if (url.hash && target.endsWith('.html')) {
      await page.goto(href);
      assert.equal(await page.locator(`[id="${decodeURIComponent(url.hash.slice(1))}"]`).count(), 1, href);
    } else {
      assert.ok((await readFile(target)).length > 0, href);
    }
  }
  assert.ok(runs > 0);
  console.log(`PASS D6: local links resolve within session; ${runs} replay fragments load their named recording offline.`);
} finally { await browser.close(); }
