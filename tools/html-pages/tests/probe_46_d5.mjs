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
test('D5: the linked attention activity realizes the described soft lookup', async t => {
  const page = await open(t), s = await slide(page,'attention');
  for (const word of ['soft database lookup','query','key','softmax','values']) assert.ok((await s.textContent()).includes(word));
  await slide(page,'attention-lab');
  await page.locator('#attention-lab a[href="labs/attention.html"]').click();
  await page.waitForFunction(()=>!document.querySelector('[data-attn-scale]').disabled);
  await page.locator('[data-attn-scale]').evaluate(e=>{e.value='0';e.dispatchEvent(new Event('input',{bubbles:true}));});
  const weights = await page.locator('[data-attn-weight]').allTextContents();
  assert.equal(weights.length,4);
  weights.forEach(w=>assert.match(w,/25(?:\.0)?%/));
  const values = await page.locator('[data-attn-value]').evaluateAll(es=>es.map(e=>[Number(e.dataset.x),Number(e.dataset.y)]));
  const output = await page.locator('[data-attn-output]').evaluate(e=>[Number(e.dataset.x),Number(e.dataset.y)]);
  for(let axis=0;axis<2;axis++) assert.ok(Math.abs(output[axis]-values.reduce((sum,v)=>sum+v[axis],0)/values.length)<1e-9);
});
