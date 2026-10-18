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
test('D2: readable conditional, exact joint product, and board talk track', async t => {
  const page = await open(t,{javaScriptEnabled:false}), s = page.locator('#factorization');
  const formulas = await s.locator('.formula').allTextContents();
  assert.equal(norm(formulas[0]),'p(xt | x<t)');
  assert.equal(norm(formulas[1]),'p(x1, …, xT) = ∏t=1T p(xt | x<t)');
  assert.equal(await s.locator('.formula').nth(1).locator('sup').textContent(),'T');
  assert.equal(await s.locator('.formula').nth(1).locator('sub').nth(2).textContent(),'t=1');
  const text = norm(await s.textContent());
  for (const concept of ['chain rule','joint distribution','exactly','Autoregression','empty','end-of-sequence']) assert.ok(text.includes(concept),concept);
  assert.match(await s.locator('.speaker-notes').textContent(),/Write p\(x_t \| x_<t\) on the board/);
});
