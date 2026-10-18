import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../browser.mjs';
const root = process.cwd();
const cursus = path.join(root, 'sessions/01-fundamentals/cursus');
const deck = path.join(cursus, '01-sampler.html');
const norm = s => s.replace(/\s+/g, ' ').trim();
async function open(t, options = {}) {
  const browser = await chromium.launch();
  const context = await browser.newContext({offline: true, viewport: {width:1280,height:720}, ...options});
  const requests = [], errors = [];
  await context.route(/^https?:/, route => { requests.push(route.request().url()); return route.abort(); });
  const page = await context.newPage();
  page.on('pageerror', e => errors.push(e.message));
  t.after(async () => { await browser.close(); assert.deepEqual(requests, [], 'offline runtime'); assert.deepEqual(errors, [], 'no browser exceptions'); });
  await page.goto(pathToFileURL(deck).href);
  return page;
}
async function slide(page, id) {
  await page.goto(pathToFileURL(deck).href + '#' + id);
  await page.locator('#'+id).waitFor({state:'visible'});
  return page.locator('#'+id);
}
test('D1: notes remain usable on every slide and at presentation sizes', async t => {
  const page = await open(t);
  for (const viewport of [{width:1440,height:900},{width:1280,height:720},{width:390,height:844}]) {
    await page.setViewportSize(viewport);
    const ids = await page.locator('[data-slide]').evaluateAll(es => es.map(e=>e.id));
    assert.ok(ids.length > 1);
    for (const id of ids) {
      const s = await slide(page,id), notes = s.locator('details.speaker-notes');
      assert.equal(await notes.count(),1);
      assert.ok((await notes.locator('.notes-body').textContent()).trim().length > 0);
      if (viewport.width >= 800) assert.ok(await s.evaluate(e=>e.scrollHeight <= e.clientHeight+1), id+' fits');
      const summary = notes.locator('summary');
      await summary.focus(); await page.keyboard.press('Enter');
      assert.equal(await notes.evaluate(e=>e.open),true);
      assert.equal(await notes.locator('.notes-body').isVisible(),true);
      await summary.focus(); await page.keyboard.press('Enter');
      assert.equal(await notes.evaluate(e=>e.open),false);
    }
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  }
  await page.emulateMedia({media:'print'});
  assert.ok(await page.locator('[data-slide]').evaluateAll(es=>es.every(e=>e.checkVisibility())));
  assert.ok(await page.locator('.notes-body').evaluateAll(es=>es.every(e=>e.checkVisibility()&&e.scrollHeight<=e.clientHeight+1)));
});
