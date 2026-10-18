import assert from 'node:assert/strict';
import { access, realpath } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { chromium } from './browser.mjs';

const session = await realpath('sessions/01-fundamentals');
const deckURL = pathToFileURL(path.join(session, 'cursus/03-agent.html')).href;
const browser = await chromium.launch();
try {
  const context = await browser.newContext({ offline: true });
  const page = await context.newPage();
  const errors = [], remote = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => { if (/^https?:/.test(r.url())) remote.push(r.url()); });
  await page.goto(deckURL);
  const links = await page.locator('[data-slide] a[href]').evaluateAll(nodes => nodes.map(a => a.href).filter(h => h.startsWith('file:')));
  assert.ok(links.some(h => h.endsWith('/demos/agent/loop.md')));
  assert.ok(links.some(h => h.endsWith('/demos/agent/context-bomb.md')));
  const replay = [...new Set(links.filter(h => new URL(h).hash.startsWith('#run=')))];
  assert.ok(replay.some(h => h.includes('loop-claude')) && replay.some(h => h.includes('loop-codex')));
  assert.ok(replay.some(h => h.includes('bomb-claude')) && replay.some(h => h.includes('bomb-codex')));
  for (const link of new Set(links)) {
    const url = new URL(link), target = await realpath(fileURLToPath(url));
    assert.ok(target.startsWith(session + path.sep), link);
    await access(target);
    if (!url.hash || url.hash.startsWith('#run=')) continue;
    await page.goto(link);
    assert.equal(await page.locator('[id]').evaluateAll((nodes, id) => nodes.filter(n => n.id === id).length, decodeURIComponent(url.hash.slice(1))), 1, link);
  }
  for (const link of replay) {
    await page.goto(link);
    const id = decodeURIComponent(new URL(link).hash.slice(5));
    assert.equal(await page.locator('#run-select').inputValue(), id, link);
    const panel = page.locator('[data-run-panel]').filter({ visible: true });
    assert.equal(await panel.count(), 1);
    assert.equal(await panel.getAttribute('data-run-panel'), id);
    const stepper = panel.locator('[data-stepper]');
    assert.equal(await stepper.getAttribute('data-step-current'), '0');
    const count = await panel.locator('[data-step]').count();
    assert.ok(count > 0, id);
    if (count > 1) {
      await panel.locator('[data-step-next]').click();
      assert.equal(await stepper.getAttribute('data-step-current'), '1');
    } else {
      assert.equal(await panel.locator('[data-step-next]').isDisabled(), true);
    }
    await panel.locator('[data-step-reset]').click();
    assert.equal(await stepper.getAttribute('data-step-current'), '0');
  }
  assert.deepEqual(errors, []);
  assert.deepEqual(remote, []);
  console.log(`PASS: local targets and ${replay.length} offline replay links, selection, next and reset`);
} finally { await browser.close(); }
