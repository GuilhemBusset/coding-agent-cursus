import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { chromium } from './browser.mjs';

const session = path.resolve('sessions/01-fundamentals');
const deck = path.join(session, 'cursus/02-thinking.html');
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, reducedMotion: 'reduce' });
const errors = [], requests = [];
await context.route(/^https?:/, route => { requests.push(route.request().url()); return route.abort(); });
const page = await context.newPage();
page.on('pageerror', error => errors.push(String(error)));
try {
  await page.goto(pathToFileURL(deck).href);
  const ids = await page.locator('[data-slide]').evaluateAll(slides => slides.map(s => s.id));
  assert.ok(ids.length > 1);
    await page.goto(`${pathToFileURL(deck).href}#repo-model`);
    await page.locator('#repo-model details summary').click();
    const text = await page.locator('#repo-model details').innerText();
    const seed = text.match(/Seed\s+(\d+)/i)?.[1];
    const error = text.match(/Model error\s+(\d+(?:\.\d+)?)/i)?.[1];
    assert.ok(seed && error, 'recipe communicates settings');
    await page.locator('#repo-model a[href$="#planner"]').click();
    await page.getByLabel('Seed', {exact:true}).fill(seed);
    await page.getByLabel('Seed', {exact:true}).dispatchEvent('change');
    await page.getByLabel('Model error', {exact:true}).evaluate((el, value) => { el.value = value; el.dispatchEvent(new Event('input', {bubbles:true})); }, error);
    await page.locator('#planner').getByRole('button', {name:'Reset', exact:true}).click();
    const values = () => page.locator('#planner [data-wm-outcome]').allTextContents();
    for (let i=0; i<100 && (await values()).some(v => v.trim() === 'Running'); i++) await page.locator('#planner').getByRole('button', {name:'Step', exact:true}).click();
    assert.deepEqual((await values()).map(v => v.trim()), ['Hit obstacle', 'Reached goal']);
    const runs = await page.evaluate(({seed,error}) => {
      const W = window.WorldModel;
      return {world:W.config.world, open:W.runOpenLoop(Number(seed),Number(error)), closed:W.runClosedLoop(Number(seed),Number(error))};
    }, {seed,error});
    const {obstacle, goal} = runs.world;
    const o = {x:obstacle.center[0],y:obstacle.center[1],r:obstacle.radius};
    const g = {x:goal.center[0],y:goal.center[1],r:goal.radius};
    function collides(a,b) {
      const dx=b[0]-a[0], dy=b[1]-a[1], d=dx*dx+dy*dy;
      const t=d ? Math.max(0,Math.min(1,((o.x-a[0])*dx+(o.y-a[1])*dy)/d)) : 0;
      return Math.hypot(a[0]+t*dx-o.x,a[1]+t*dy-o.y) <= o.r;
    }
    assert.ok(runs.open.records.some(r => collides(r.state,r.nextState)));
    assert.ok(!runs.closed.records.some(r => collides(r.state,r.nextState)));
    const last=runs.closed.records.at(-1).nextState;
    assert.ok(Math.hypot(last[0]-g.x,last[1]-g.y) <= g.r);
  assert.deepEqual(errors, []);
  assert.deepEqual(requests, [], 'no network required');
  console.log("PASS");
} finally { await browser.close(); }
