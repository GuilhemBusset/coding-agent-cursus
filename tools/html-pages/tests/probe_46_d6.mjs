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
test('D6: three training slides include genuine contiguous base and assistant fixture outputs', async t => {
  const page = await open(t,{javaScriptEnabled:false});
  for(const id of ['pretraining','post-training','rlvr']) assert.equal(await page.locator('#'+id+'[data-slide]').count(),1);
  const pre = norm(await page.locator('#pretraining').textContent());
  assert.match(pre,/lossy compression/); assert.match(pre,/lossless/); assert.match(pre,/metaphor/);
  assert.equal(await page.locator('#pretraining a[href="https://arxiv.org/abs/2309.10668"]').count(),1);
  const fixture = JSON.parse(await readFile(path.join(cursus,'fixtures/base_vs_instruct.json'),'utf8'));
  const item = fixture.items.find(i=>i.id==='factual');
  const quotes = await page.locator('#post-training blockquote').evaluateAll(es=>es.map(e=>Array.from(e.querySelectorAll('p')).map(p=>p.textContent).join(' ')));
  assert.equal(norm(quotes[0]),norm(item.prompt));
  assert.ok(norm(item.base.text).includes(norm(quotes[1])));
  assert.equal(norm(quotes[2]),norm(item.instruct.text));
  assert.equal(item.instruct.stop,'eos');
  const rl = norm(await page.locator('#rlvr').textContent());
  for(const concept of ['verifiable rewards','program scores','reward 1','reinforce','checker']) assert.ok(rl.toLowerCase().includes(concept),concept);
});
