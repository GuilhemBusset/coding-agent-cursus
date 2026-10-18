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
test('D3: the token illustration agrees with its data and both code-pivot fallbacks run', async t => {
  const page = await open(t,{javaScriptEnabled:false});
  const data = JSON.parse(await readFile(path.join(cursus,'fixtures/next_token.json'),'utf8'));
  const token = data.prompts.find(p=>p.prompt===' strawberry').prompt_tokens;
  assert.equal(token.length,1);
  const text = norm(await page.locator('#tokens').textContent());
  assert.match(text,/integer IDs/);
  assert.ok(text.includes('ID '+token[0].id));
  assert.equal(await page.locator('#strawberry a[href="demos/model/strawberry.md"]').count(),1);
  assert.match(await page.locator('#strawberry').textContent(),/writes.*count_r\.py/s);
  for (const vendor of ['claude','codex']) {
    const output = execFileSync('python3',['strawberry.py','--replay','--pivot','--via',vendor],{cwd:path.join(cursus,'demos/model'),encoding:'utf8'});
    assert.match(output,/146/);
    assert.match(output,/count_r\.py/);
    assert.match(output,/true count: 146/);
  }
});
