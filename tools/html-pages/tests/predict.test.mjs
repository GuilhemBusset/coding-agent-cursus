import test from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from '../browser.mjs';
import { openPage, predictRoots, chooseAll, initialPredict, count, enabled, focused, textOf } from './component-helpers.mjs';

async function contract(root) {
  for (const name of ['lock', 'reveal', 'reset']) await count(root.locator(`button[data-predict-${name}]`), 1);
  await count(root.locator('[data-predict-status][role=status]'), 1);
  for (const q of await root.locator('fieldset[data-predict-question]').all()) {
    assert.ok(await textOf(q.locator('legend')));
    await count(q.locator('input[type=radio][data-correct]'), 1);
    assert.ok(await q.locator('input[type=radio]').count() >= 2);
    for (const radio of await q.locator('input[type=radio]').all()) {
      assert.ok(await radio.evaluate(el => Array.from(el.labels || []).some(label => label.textContent.trim())), 'native radios need labels');
    }
    await count(q.locator('[data-predict-result]'), 1);
    await count(q.locator('[data-predict-answer]'), 1);
    assert.ok((await textOf(q.locator('[data-predict-answer]'))).length > 10, 'authored answer includes an explanation');
  }
}

async function reveal(root, correct) {
  const lock = root.locator('[data-predict-lock]');
  const show = root.locator('[data-predict-reveal]');
  await enabled(lock);
  await enabled(show, false);
  await lock.focus();
  await lock.press('Enter');
  await enabled(lock, false);
  await enabled(show);
  await focused(show);
  for (const radio of await root.locator('input[type=radio]').all()) await enabled(radio, false);
  for (const answer of await root.locator('[data-predict-answer]').all()) assert.equal(await answer.isVisible(), false);
  await show.press('Enter');
  await enabled(show, false);
  await focused(root.locator('[data-predict-reset]'));
  for (const q of await root.locator('[data-predict-question]').all()) {
    const answer = q.locator('[data-predict-answer]');
    assert.equal(await answer.isVisible(), true);
    assert.equal(await answer.evaluate(el => el.hidden), false);
    const label = await q.locator('input[data-correct]').evaluate(el => Array.from(el.labels).map(l => l.textContent.trim()).join(' '));
    assert.equal(await textOf(q.locator('[data-predict-result]')), correct ? 'Correct.' : `Not quite. The answer is ${label}.`);
    assert.ok((await answer.ariaSnapshot()).length > 0, 'revealed explanation is accessible');
  }
}

test('D1: single card separates choice, lock, reveal and reset, with keyboard focus', { timeout: 45000 }, async t => {
  const page = await openPage(t, chromium);
  const { single, ticket } = await predictRoots(page);
  await contract(single);
  await contract(ticket);
  await initialPredict(single);
  await initialPredict(ticket);
  for (const correct of [false, true]) {
    await chooseAll(single, correct);
    await reveal(single, correct);
    await initialPredict(ticket);
    await single.locator('[data-predict-reset]').press('Enter');
    await focused(single.locator('input[type=radio]').first());
    await initialPredict(single);
  }
  // Native arrow selection, rather than a script pretending to select a radio.
  const radios = single.locator('input[type=radio]');
  await radios.first().focus();
  await page.keyboard.press('ArrowRight');
  await count(single.locator('input:checked'), 1);
  await enabled(single.locator('[data-predict-lock]'));
  await enabled(single.locator('[data-predict-reveal]'), false);
  await single.locator('[data-predict-lock]').click();
  await single.locator('[data-predict-reset]').click();
  await initialPredict(single); // Reset is also valid before revealing.
});

test('D1: exit ticket requires every answer and keeps roots independent', { timeout: 45000 }, async t => {
  const page = await openPage(t, chromium);
  const { single, ticket } = await predictRoots(page);
  await ticket.locator('[data-predict-question]').first().locator('input[data-correct]').check();
  await enabled(ticket.locator('[data-predict-lock]'), false);
  await enabled(ticket.locator('[data-predict-reveal]'), false);
  await chooseAll(single, false);
  await single.locator('[data-predict-lock]').click();
  await chooseAll(ticket);
  await reveal(ticket, true);
  await enabled(single.locator('[data-predict-reveal]'));
  assert.equal(await single.locator('[data-predict-answer]').isVisible(), false);
  await ticket.locator('[data-predict-reset]').click();
  await initialPredict(ticket);
  await enabled(single.locator('[data-predict-reveal]'));
  await count(single.locator('input:checked'), 1);
  await single.locator('[data-predict-reveal]').click();
  assert.match(await textOf(single.locator('[data-predict-result]')), /^Not quite\. The answer is .+\.$/);
  await initialPredict(ticket);
  // A ticket must score each question, not copy the first question's result to all.
  const questions = ticket.locator('[data-predict-question]');
  await questions.nth(0).locator('input[data-correct]').check();
  await questions.nth(1).locator('input[type=radio]:not([data-correct])').first().check();
  await ticket.locator('[data-predict-lock]').click();
  await ticket.locator('[data-predict-reveal]').click();
  assert.equal(await textOf(questions.nth(0).locator('[data-predict-result]')), 'Correct.');
  const label = await questions.nth(1).locator('input[data-correct]').evaluate(el => Array.from(el.labels).map(l => l.textContent.trim()).join(' '));
  assert.equal(await textOf(questions.nth(1).locator('[data-predict-result]')), `Not quite. The answer is ${label}.`);
  for (const answer of await ticket.locator('[data-predict-answer]').all()) assert.equal(await answer.isVisible(), true);
});

test('D1: without JavaScript answers and explanations remain readable', async t => {
  const page = await openPage(t, chromium, { javaScriptEnabled: false });
  const { single, ticket } = await predictRoots(page);
  for (const root of [single, ticket]) {
    await contract(root);
    for (const answer of await root.locator('[data-predict-answer]').all()) assert.equal(await answer.isVisible(), true);
    for (const button of await root.locator('button').all()) await enabled(button, false);
    for (const radio of await root.locator('input[type=radio]').all()) await enabled(radio);
  }
});
