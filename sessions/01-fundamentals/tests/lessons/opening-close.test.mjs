import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from '../../../../tools/html-pages/browser.mjs';
import { openPage, repoRoot, enabled, focused, textOf, eventually } from '../../../../tools/html-pages/tests/component-helpers.mjs';

// The opening and close decks: their polls (the cold-open return and the exit ticket) work in the room.
// The predict component itself is predict.test.mjs's; here, each deck's authored questions are well
// formed, and a keyboard round scores each question on its own without turning the slide.
// check-page covers the rest of every deck: layout, accessibility, navigation, links, no-JS and print.
const decks = {
  opening: path.join(repoRoot, 'sessions/01-fundamentals/cursus/00-opening.html'),
  close: path.join(repoRoot, 'sessions/01-fundamentals/cursus/99-close.html'),
};

async function tabTo(page, target) {
  const limit = 2 * await page.locator('a[href], button, input, select, textarea, summary, [tabindex]').count() + 4;
  for (let i = 0; i < limit; i++) {
    if (await target.evaluate(el => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  assert.fail('keyboard Tab order must reach the requested control');
}

// Answers every question by native arrow keys, right on even questions and wrong on odd ones, so a
// constant score or one question's result copied to the others fails; then locks, reveals and resets.
async function keyboardRound(page, root) {
  const questions = await root.locator('fieldset[data-predict-question]').all();
  const expected = [];
  for (const [i, question] of questions.entries()) {
    const radios = question.locator('input[type="radio"]');
    const flags = await radios.evaluateAll(els => els.map(el => el.hasAttribute('data-correct')));
    const index = flags.findIndex(flag => flag === (i % 2 === 0));
    expected.push(i % 2 === 0);
    await radios.nth((index + flags.length - 1) % flags.length).focus();
    await page.keyboard.press('ArrowRight');
    assert.equal(await radios.nth(index).isChecked(), true);
  }
  const lock = root.locator('[data-predict-lock]'), reveal = root.locator('[data-predict-reveal]'), reset = root.locator('[data-predict-reset]');
  await tabTo(page, lock);
  await page.keyboard.press('Enter');
  await focused(reveal);
  await page.keyboard.press('Enter');
  await focused(reset);
  for (const [i, question] of questions.entries()) {
    const label = await question.locator('input[data-correct]').evaluate(el => [...el.labels].map(l => l.textContent.trim()).join(' '));
    assert.equal(await textOf(question.locator('[data-predict-result]')), expected[i] ? 'Correct.' : `Not quite. The answer is ${label}.`);
    assert.equal(await question.locator('[data-predict-answer]').isVisible(), true);
  }
  assert.equal(await textOf(root.locator('[data-predict-status]')), `Revealed: ${expected.filter(Boolean).length} of ${questions.length} correct.`);
  await page.keyboard.press('Enter');
  await focused(root.locator('input[type="radio"]').first());
  assert.equal(await root.locator('input:checked').count(), 0, 'Reset clears the answers');
  await enabled(lock, false);
}

test('opening and close decks', async t => {
  const page = await openPage(t, chromium, { file: decks.opening });
  for (const [name, file] of Object.entries(decks)) {
    if (name !== 'opening') await page.goto(pathToFileURL(file).href);

    await t.test(`${name}: each poll question has its own radio group and exactly one right answer`, async () => {
      const questions = await page.locator('[data-predict] fieldset[data-predict-question]').evaluateAll(els => els.map(el => ({
        names: [...new Set([...el.querySelectorAll('input[type="radio"]')].map(radio => radio.name))],
        choices: el.querySelectorAll('input[type="radio"]').length,
        correct: el.querySelectorAll('input[type="radio"][data-correct]').length,
      })));
      assert.ok(questions.length > 0, 'the deck has a poll');
      for (const question of questions) {
        assert.equal(question.names.length, 1, 'one radio group per question');
        assert.ok(question.names[0] && question.choices >= 2, 'a named choice');
        assert.equal(question.correct, 1, 'exactly one right answer');
      }
      const names = questions.map(question => question.names[0]);
      assert.equal(new Set(names).size, names.length, 'no two questions share a radio group');
    });

    await t.test(`${name}: each poll scores by keyboard, and its arrow keys never turn the slide`, async () => {
      const polls = await page.locator('section[data-slide]:has([data-predict])').evaluateAll(els => els.map(el => el.id));
      assert.ok(polls.length > 0, 'the deck has a poll slide');
      for (const id of polls) {
        await page.evaluate(id => { location.hash = id; }, id);
        const visible = () => page.locator('section[data-slide]').evaluateAll(els => els.filter(el => el.checkVisibility()).map(el => el.id));
        await eventually(async () => assert.deepEqual(await visible(), [id]), `on #${id}`);
        for (const root of await page.locator(`section[data-slide]#${id} [data-predict]`).all()) await keyboardRound(page, root);
        assert.deepEqual(await visible(), [id], 'the radios’ arrow keys left the deck on its slide');
      }
    });
  }
});
