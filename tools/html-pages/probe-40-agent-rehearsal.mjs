import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { chromium } from './browser.mjs';

test('A2 agent part: 45-minute plan includes activities and the revealed results fit presentation sizes', async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const url = pathToFileURL(path.resolve('sessions/01-fundamentals/cursus/02-thinking.html')).href;
    await page.goto(url);
    const times = await page.locator('[data-slide] details.notes').evaluateAll(notes => notes.map(n => Number(n.dataset.minutes)));
    assert.ok(times.every(n => Number.isFinite(n) && n > 0));
    assert.equal(times.reduce((a,b) => a+b, 0), 45);
    const record = readFileSync('sessions/01-fundamentals/cursus/02-thinking/rehearsal.md', 'utf8');
    const rows = [...record.matchAll(/^\|\s*(\d+)\s*\|[^|]+\|\s*([\d.]+)\s*\|/gm)].map(m => Number(m[2]));
    assert.deepEqual(rows, times, 'the instructor schedule agrees with the delivered notes');
    assert.match(record, /Cuts to make/);
    assert.match(record, /Observed rehearsal/);
    for (const viewport of [{ width:1280,height:720 }, { width:1440,height:900 }]) {
      await page.setViewportSize(viewport);
      await page.goto(url + '#effort-demo');
      if (await page.locator('#effort-demo .reveal').getAttribute('open') === null) await page.locator('#effort-demo .reveal summary').click();
      assert.ok(await page.locator('#effort-demo .reveal table').isVisible());
      assert.ok(await page.locator('#effort-demo').evaluate(s => s.scrollHeight <= s.clientHeight + 1));
    }
    await page.emulateMedia({ media: 'print' });
    assert.equal(await page.locator('[data-slide]:visible').count(), times.length);
    assert.equal(await page.locator('details.notes[open]').count(), times.length);
  } finally { await browser.close(); }
});
