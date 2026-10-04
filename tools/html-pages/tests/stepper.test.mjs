import test from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from '../browser.mjs';
import { openPage, fixture, stepperMarkup, stepState, count, focused } from './component-helpers.mjs';

test('D4: sample clicks, keyboard, boundaries, reset and event indexes agree', { timeout: 45000 }, async t => {
  const page = await openPage(t, chromium);
  const root = page.locator('[data-stepper]');
  await count(root, 1);
  const stage = root.locator('[data-step-stage][tabindex="0"]');
  await count(stage, 1);
  assert.equal(await root.locator('[data-step-controls]').isVisible(), true);
  await root.evaluate(el => { window.stepEvents = []; el.addEventListener('cursus:step', event => window.stepEvents.push(event.detail.index)); });
  const indexes = [];
  async function check(index) {
    indexes.push(index);
    await stepState(root, index, 4);
    assert.deepEqual(await page.evaluate(() => window.stepEvents), indexes, 'one event for every move');
  }
  await stepState(root, 0, 4);
  for (let i = 1; i < 4; i++) { await root.locator('[data-step-next]').click(); await check(i); }
  await focused(stage);
  for (let i = 2; i >= 0; i--) { await root.locator('[data-step-prev]').click(); await check(i); }
  await focused(stage);
  for (const [key, index] of [['End', 3], ['ArrowLeft', 2], ['Home', 0], ['ArrowRight', 1]]) {
    await stage.press(key);
    await check(index);
  }
  await root.locator('[data-step-reset]').click();
  await check(0);
  // Observe defaultPrevented after the component handles the event on the stage.
  for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End']) {
    assert.equal(await stage.evaluate((el, key) => {
      const e = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
      el.dispatchEvent(e); return e.defaultPrevented;
    }, key), true);
  }
});

test('D4: only the bare stage handles navigation; nested controls and sibling steppers stay independent', { timeout: 60000 }, async t => {
  const controls = `<button id="nested-button">Nested button</button><label for="range">Range</label>
    <input id="range" type="range" min="0" max="10" value="4"><label for="select">Select</label>
    <select id="select"><option>One</option><option>Two</option></select><label for="text">Text</label>
    <input id="text" value="editable"><details open><summary id="summary">Details</summary>Content</details>
    <a id="link" href="#content">Link</a>`;
  const page = await openPage(t, chromium, { file: await fixture(t, stepperMarkup('one', 3, controls) + stepperMarkup('two', 5)) });
  const one = page.locator('#one'), two = page.locator('#two'), stage = one.locator('[data-step-stage]');
  await stepState(one, 0, 3);
  await stepState(two, 0, 5);
  for (const selector of ['#nested-button', '#range', '#select', '#text', '#summary', '#link', '[data-step-next]', '[data-step-reset]']) {
    const target = one.locator(selector);
    for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End']) {
      await target.press(key);
      await stepState(one, 0, 3);
    }
  }
  await one.locator('#range').fill('4');
  await one.locator('#range').press('ArrowRight');
  assert.equal(await one.locator('#range').inputValue(), '5', 'range keeps native arrow behavior');
  for (const modifier of ['shiftKey', 'ctrlKey', 'altKey', 'metaKey']) {
    for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End']) {
      assert.equal(await stage.evaluate((el, { modifier, key }) => {
        const e = new KeyboardEvent('keydown', { key, [modifier]: true, bubbles: true, cancelable: true });
        el.dispatchEvent(e); return e.defaultPrevented;
      }, { modifier, key }), false);
      await stepState(one, 0, 3);
    }
  }
  await one.locator('[data-step-next]').click();
  for (const selector of ['[data-step-prev]', '[data-step-next]', '[data-step-reset]']) {
    for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End']) {
      await one.locator(selector).press(key);
      await stepState(one, 1, 3);
    }
  }
  await stepState(two, 0, 5);
  await two.locator('[data-step-stage]').press('End');
  await stepState(two, 4, 5);
  await one.locator('[data-step-reset]').click();
  await stepState(one, 0, 3);
  await stepState(two, 4, 5);
});

test('D4: no-JS and print show every step; returning to screen restores state', async t => {
  const noJS = await openPage(t, chromium, { javaScriptEnabled: false });
  await count(noJS.locator('[data-stepper] [data-step]'), 4);
  for (const step of await noJS.locator('[data-step]').all()) assert.equal(await step.isVisible(), true);
  assert.equal(await noJS.locator('[data-step-controls]').isVisible(), false);
  const page = await openPage(t, chromium);
  const root = page.locator('[data-stepper]');
  await root.locator('[data-step-next]').click();
  await page.emulateMedia({ media: 'print' });
  for (const step of await root.locator('[data-step]').all()) assert.equal(await step.isVisible(), true);
  assert.equal(await root.locator('[data-step-controls]').isVisible(), false);
  await page.emulateMedia({ media: 'screen' });
  await stepState(root, 1, 4);
});
