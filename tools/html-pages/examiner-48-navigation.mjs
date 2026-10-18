import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
import {chromium} from './browser.mjs';

const url = pathToFileURL(path.resolve('sessions/01-fundamentals/cursus/03-agent.html')).href;
const browser = await chromium.launch();
try {
  const page = await browser.newPage({viewport:{width:1280,height:720}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route(/^https?:/, route => route.abort());
  await page.goto(url);
  const ids = await page.locator('[data-slide]').evaluateAll(nodes => nodes.map(n => n.id));
  assert.ok(ids.length > 1);
  for (let i=0; i<ids.length; i++) {
    assert.equal(await page.locator('[data-slide]:visible').getAttribute('id'), ids[i]);
    const fits = await page.locator('#'+ids[i]).evaluate(s => s.scrollHeight <= s.clientHeight+1);
    assert.ok(fits, ids[i]+' must fit the laptop viewport');
    if (i+1 < ids.length) await page.locator('[data-next]').click();
  }
  assert.ok(await page.locator('[data-next]').isDisabled());
  await page.locator('[data-slide]:visible').focus();
  await page.keyboard.press('Home');
  assert.equal(await page.locator('[data-slide]:visible').getAttribute('id'), ids[0]);
  for (const id of ['loop-demo','bomb-demo']) {
    await page.goto(url+'#'+id);
    const reveal = page.locator('#'+id+' .reveal');
    await reveal.locator('summary').focus();
    await page.keyboard.press('Enter');
    assert.ok(await reveal.evaluate(d => d.open));
    assert.ok(await reveal.locator('table').isVisible());
    assert.ok(await page.locator('#'+id).evaluate(s => s.scrollHeight <= s.clientHeight+1));
    await page.keyboard.press('Enter');
    assert.equal(await reveal.evaluate(d => d.open), false);
    assert.ok(await page.locator('#'+id+' .cols').isVisible());
  }
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.locator('[data-slide]:visible').count(), ids.length);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.emulateMedia({media:'print'});
  assert.equal(await page.locator('[data-slide]:visible').count(), ids.length);
  assert.deepEqual(errors, []);
  console.log('PASS: file:// navigation, demo reveals, laptop fit, mobile and print');
} finally { await browser.close(); }
