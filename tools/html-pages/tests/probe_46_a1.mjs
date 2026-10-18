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
test('A1 agent portion: notes and schedule agree on 45 minutes while rehearsal remains explicitly pending', async t => {
  const page = await open(t,{javaScriptEnabled:false});
  const slides = await page.locator('[data-slide]').evaluateAll(es=>es.map(e=>({minutes:Number(e.dataset.minutes),summary:e.querySelector('.speaker-notes summary').textContent})));
  assert.equal(slides.reduce((sum,s)=>sum+s.minutes,0),45);
  for(const s of slides) assert.match(s.summary,new RegExp('· '+s.minutes+' min$'));
  const record = await readFile(path.join(cursus,'01-sampler/rehearsal.md'),'utf8');
  const rows = record.split('\n').filter(l=>/^\| \d+ \|/.test(l)).map(l=>l.split('|').map(s=>s.trim()));
  assert.deepEqual(rows.map(r=>Number(r[3])),slides.map(s=>s.minutes));
  assert.match(record,/Status: pending/);
  for(const field of ['Date:','Presenter:','Observed minutes','Cuts made','Result']) assert.ok(record.includes(field));
});
