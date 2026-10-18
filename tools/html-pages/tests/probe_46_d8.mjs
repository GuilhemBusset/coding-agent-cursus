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
test('D8: all four activity links launch offline and Back recovers the correct slide', async t => {
  const page = await open(t);
  for (const [id,lab] of [['tokenizer-lab','tokenizer'],['next-token-lab','next-token'],['tiny-lm-lab','tiny-lm'],['attention-lab','attention']]) {
    await slide(page,id);
    await page.locator('#'+id+' a[href="labs/'+lab+'.html"]').click();
    assert.equal(new URL(page.url()).protocol,'file:');
    assert.ok(page.url().endsWith('/labs/'+lab+'.html'));
    assert.ok((await page.locator('h1').textContent()).trim());
    await page.goBack();
    await page.locator('#'+id).waitFor({state:'visible'});
    assert.equal(new URL(page.url()).hash,'#'+id);
    assert.equal(await page.locator('[data-slide]:visible').count(),1);
  }
  const s = await slide(page,'strawberry');
  const href = await s.locator('a[href="demos/model/strawberry.md"]').getAttribute('href');
  assert.match(await readFile(path.join(cursus,href),'utf8'),/## Run/);
});
