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
test('D4: displayed distribution matches recorded logits and seeded forward passes reproduce', async t => {
  const page = await open(t), s = await slide(page,'distribution');
  const fixture = JSON.parse(await readFile(path.join(cursus,'fixtures/next_token.json'),'utf8'));
  const prompt = fixture.prompts.find(p=>p.prompt==='The capital of France is');
  assert.ok(prompt);
  const rows = await s.locator('[data-prob-row]').evaluateAll(es=>es.map(e=>({p:Number(e.dataset.value),label:e.querySelector('[data-prob-label] code').textContent})));
  assert.equal(rows.length,5);
  for (let i=0;i<rows.length;i++) {
    assert.equal(rows[i].label,prompt.top[i].text.replaceAll(' ','␣'));
    assert.ok(Math.abs(rows[i].p-Math.exp(prompt.top[i].logit-prompt.logsumexp))<0.0001);
  }
  assert.match(await s.textContent(),/softmax\(z\/T\)/);
  const close = await slide(page,'system-1');
  assert.match(await close.textContent(),/Fixed compute per token/);
  await page.goto(pathToFileURL(path.join(cursus,'labs/tiny-lm.html')).href);
  await page.locator('#tlm-step').waitFor({state:'visible'});
  await page.waitForFunction(()=>!document.querySelector('#tlm-step').disabled);
  for(let i=0;i<5;i++) await page.locator('#tlm-step').click();
  assert.equal(await page.locator('#tlm-text button').count(),5);
  const first = await page.locator('#tlm-text').textContent();
  await page.locator('#tlm-reset').click();
  for(let i=0;i<5;i++) await page.locator('#tlm-step').click();
  assert.equal(await page.locator('#tlm-text').textContent(),first);
});
