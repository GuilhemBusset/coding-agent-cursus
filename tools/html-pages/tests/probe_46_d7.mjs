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
test('D7: visible limitations distinguish truth from fluency and label the reversed objective', async t => {
  const page = await open(t,{javaScriptEnabled:false});
  const cutoff = norm(await page.locator('#cutoff').textContent());
  assert.match(cutoff,/Knowledge cutoff/); assert.match(cutoff,/Context can carry newer facts/);
  const hallucination = norm(await page.locator('#hallucination').textContent());
  for(const concept of ['No truth oracle','structural','does not mean always wrong','outside the model']) assert.ok(hallucination.includes(concept));
  const stake = page.locator('#or-stake');
  assert.match(await stake.textContent(),/Illustrative/); assert.match(await stake.textContent(),/least total cost/);
  const code = await stake.locator('pre code').allTextContents();
  assert.equal(code.length,2);
  assert.ok(code[0].includes('kMinimize'));
  assert.equal(code[1],code[0].replace('kMinimize','kMaximize'));
  assert.match(await stake.textContent(),/Only the first, minimize, matches/);
});
