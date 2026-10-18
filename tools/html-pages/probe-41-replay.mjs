import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import { chromium } from './browser.mjs';

test('Issue 41 fallbacks play offline across all three demos', async () => {
  const base = path.resolve('sessions/01-fundamentals/cursus');
  const catalog = JSON.parse(await readFile(path.join(base, 'fixtures/runs/agent-demos.json'), 'utf8'));
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      if (!route.request().url().startsWith('file:')) {
        errors.push(route.request().url());
        return route.abort();
      }
      return route.continue();
    });
    for (const id of ['loop-codex-run2', 'plan-claude-run1-plan', 'bomb-claude-run2-with-tool-search-off']) {
      const run = catalog.runs.find(row => row.id === id);
      assert.ok(run);
      await page.goto(pathToFileURL(path.join(base, 'labs/agent-loop.html')).href + '#run=' + id);
      assert.equal(await page.getByRole('combobox').inputValue(), id);
      const stage = page.locator('[data-stepper]:visible [data-step-stage]');
      await stage.focus();
      await stage.press('End');
      const step = page.locator('[data-stepper]:visible [data-step]:visible');
      assert.equal(await step.locator('pre').textContent(), run.steps.at(-1).text);
      assert.equal(await page.locator('[data-stepper]:visible [data-step-next]').isDisabled(), true);
      await stage.press('Home');
      assert.equal(await step.locator('pre').textContent(), run.steps[0].text);
    }
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
});
