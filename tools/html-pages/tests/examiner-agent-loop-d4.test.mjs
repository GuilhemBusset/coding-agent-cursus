import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { chromium } from '../browser.mjs';
import { openPage } from './component-helpers.mjs';

const root = process.cwd();
const cursus = path.join(root, 'sessions/01-fundamentals/cursus');
const file = path.join(cursus, 'labs/agent-loop.html');
const fixtures = path.join(cursus, 'fixtures/runs');
const tasks = readdirSync(fixtures).filter(n => /-(claude|codex)\.json$/.test(n))
  .map(n => JSON.parse(readFileSync(path.join(fixtures, n), 'utf8')));
const panel = p => p.locator('[data-run-panel]:visible');
async function open(t) { return openPage(t, chromium, { file, offline: true }); }
async function choose(p, id) { await p.getByRole('combobox').selectOption(id); }

test('D4: each same-task pair has independent controllers and stacks on mobile', async t => {
  const p = await open(t);
  for (const task of new Set(tasks.map(r => r.meta.task))) {
    await choose(p, `${task}-codex`);
    await p.getByRole('checkbox', { name: /side by side/i }).check();
    assert.equal(await panel(p).count(), 2);
    const a = p.locator(`[data-run-panel="${task}-claude"]`), b = p.locator(`[data-run-panel="${task}-codex"]`);
    assert.ok(await a.isVisible() && await b.isVisible());
    await a.locator('[data-step-next]').click();
    assert.equal(await a.locator('[data-stepper]').getAttribute('data-step-current'), '1');
    assert.equal(await b.locator('[data-stepper]').getAttribute('data-step-current'), '0');
    const aa = await a.boundingBox(), bb = await b.boundingBox(); assert.ok(aa.x + aa.width <= bb.x + 1);
    if (task === 'flipped-sense') {
      await p.setViewportSize({ width: 390, height: 844 });
      assert.ok((await b.boundingBox()).y >= (await a.boundingBox()).y + (await a.boundingBox()).height);
      assert.ok(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await p.setViewportSize({ width: 1440, height: 900 });
    }
    await p.getByRole('checkbox', { name: /side by side/i }).uncheck();
  }
});
