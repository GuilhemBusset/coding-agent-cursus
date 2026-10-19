import test from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { chromium } from '../browser.mjs';

const cursus = fileURLToPath(new URL('../../../sessions/01-fundamentals/cursus/', import.meta.url));
const deck = pathToFileURL(path.join(cursus, '03-agent.html')).href;

test('Act III demo links open the selected offline recording and its working stepper', async t => {
  const browser = await chromium.launch({ headless: true });
  t.after(() => browser.close());
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    if (new URL(route.request().url()).protocol === 'file:') return route.continue();
    errors.push(`External request: ${route.request().url()}`);
    return route.abort();
  });
  for (const slide of ['loop-demo', 'bomb-demo']) {
    await page.goto(`${deck}#${slide}`);
    const links = await page.locator(`#${slide} a[href*="agent-loop.html#run="]`)
      .evaluateAll(nodes => nodes.map(node => node.getAttribute('href')));
    assert.ok(links.length >= 2, `${slide} supplies replay fallbacks`);
    for (const href of links) {
      await page.goto(`${deck}#${slide}`);
      await page.locator(`#${slide} a[href="${href}"]`).click();
      const run = new URL(page.url()).hash.slice('#run='.length);
      assert.equal(run, new URL(href, deck).hash.slice('#run='.length));
      assert.equal(await page.locator('#run-select').inputValue(), run);
      const panel = page.locator(`[data-run-panel="${run}"]`);
      assert.equal(await panel.isVisible(), true);
      const stepper = panel.locator('[data-stepper]');
      assert.equal(await stepper.getAttribute('data-step-current'), '0');
      assert.ok((await stepper.locator('[data-step]:visible').innerText()).trim());
      if (await stepper.locator('[data-step]').count() > 1) {
        await stepper.locator('[data-step-next]').click();
        assert.equal(await stepper.getAttribute('data-step-current'), '1');
        await stepper.locator('[data-step-reset]').click();
        assert.equal(await stepper.getAttribute('data-step-current'), '0');
        const stage = stepper.locator('[data-step-stage]');
        await stage.focus();
        await page.keyboard.press('ArrowRight');
        assert.equal(await stepper.getAttribute('data-step-current'), '1');
        await page.keyboard.press('Home');
        assert.equal(await stepper.getAttribute('data-step-current'), '0');
      }
    }
  }
  await page.goto(`${deck}#context-window`);
  await page.locator('#context-window a[href="labs/context.html#budget-title"]').click();
  assert.ok((await page.locator('#budget-title').innerText()).trim());
  await page.goto(`${deck}#cost-growth`);
  await page.locator('#cost-growth a[href="labs/context.html#cost-title"]').click();
  assert.ok((await page.locator('#cost-title').innerText()).trim());
  assert.deepEqual(errors, []);
});
